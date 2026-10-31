import SwiftUI
import AppKit
import Combine
import CoreImage

final class JSONProcess {
    let process = Process(), output = Pipe(), input = Pipe()
    var message: ([String: Any]) -> Void
    var ended: () -> Void
    init(script: String, arguments: [String], message: @escaping ([String: Any]) -> Void, ended: @escaping () -> Void = {}) {
        self.message = message; self.ended = ended
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = [Bundle.main.resourceURL!.appendingPathComponent(script).path] + arguments
        process.standardInput = input; process.standardOutput = output; process.standardError = FileHandle.nullDevice
        var env = ProcessInfo.processInfo.environment; env["PYTHONDONTWRITEBYTECODE"] = "1"; process.environment = env
    }
    func start() throws {
        try process.run()
        DispatchQueue.global(qos: .userInitiated).async { [self] in
            var buffer = Data()
            while true {
                let data = output.fileHandleForReading.availableData
                if data.isEmpty { break }
                buffer.append(data)
                while let index = buffer.firstIndex(of: 10) {
                    let line = Data(buffer.prefix(upTo: index)); buffer.removeSubrange(...index)
                    if let value = try? JSONSerialization.jsonObject(with: line) as? [String: Any] { DispatchQueue.main.async { self.message(value) } }
                }
                if buffer.count > 262144 { buffer.removeAll() }
            }
            process.waitUntilExit(); DispatchQueue.main.async { self.ended() }
        }
    }
    func send(_ object: [String: Any]) {
        guard process.isRunning, var data = try? JSONSerialization.data(withJSONObject: object) else { return }
        data.append(10); try? input.fileHandleForWriting.write(contentsOf: data)
    }
    func stop() { try? input.fileHandleForWriting.close(); if process.isRunning { process.terminate() } }
    func closeInput() { try? input.fileHandleForWriting.close() }
}

struct AndroidDevice: Identifiable {
    let id: String
    var name: String
    var enabled: Bool
    var online: Bool
    var wireless: Bool
    var pending: Bool
}

final class Model: ObservableObject {
    @Published var outputs: [OutputDevice] = []
    @Published var selected = ""
    @Published var devices: [AndroidDevice] = []
    @Published var messages: [String: String] = [:]
    @Published var active = false
    @Published var stopping = false
    @Published var needsRecovery = false
    @Published var status = "普通模式：耳机照常使用，按需开启混音。"
    @Published var controlBusy = false
    @Published var pairingURI = ""
    @Published var remoteReady = false
    @Published var stable = true
    @Published var ready = Set<String>()
    let root = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Device Mixer")
    var journal: URL { root.appendingPathComponent("mac-restore.json") }
    var sessions: [String: JSONProcess] = [:]
    var control: JSONProcess?, remote: JSONProcess?, watcher: Process?, service: NetService?
    var watcherPipe: Pipe?, timer: Timer?, subscriptions = Set<AnyCancellable>()
    var pendingInstall: String?, scanQueued = false, afterStop: (() -> Void)?
    var bar: StatusBar?, mainWindow: NSWindow?, windowDelegate: HideWindowDelegate?
    var lastFailure: String?
    init() {
        try? FileManager.default.createDirectory(at: root, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        refreshOutputs(); _ = restoreMac(); scan(); startRemote(); watchDevices()
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            guard let self, self.active, !self.stopping else { return }
            if Route.uid(Route.current()) != self.selected || Route.channels(Route.current()) < 2 { self.status = "耳机输出改变，正在恢复普通使用。"; self.stopMix() }
        }
        objectWillChange.sink { [weak self] _ in DispatchQueue.main.async { self?.publish(); self?.bar?.refresh() } }.store(in: &subscriptions)
        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.willSleepNotification, object: nil, queue: .main) { [weak self] _ in self?.stopMix() }
    }
    func attachWindow() {
        DispatchQueue.main.async { [self] in
            if let window = NSApp.windows.first(where: { $0.title == "设备混音" }) {
                mainWindow = window; let delegate = HideWindowDelegate(); windowDelegate = delegate; window.delegate = delegate
            }
            if bar == nil { bar = StatusBar(model: self) }
        }
    }
    func refreshOutputs() {
        outputs = Route.outputs()
        if !outputs.contains(where: { $0.id == selected }) { selected = Route.uid(Route.current()) }
    }
    func publish() {
        let mode = needsRecovery && !active ? "recovery" : active ? (ready.isEmpty ? "connecting" : "mixing") : "normal"
        remote?.send(["type":"status", "data":["mode":mode,"message":status,"headphone":outputs.first(where:{$0.id == selected})?.name ?? "", "device_count":devices.filter(\.enabled).count]])
    }
    func controlAction(script: String, arguments: [String], handler: @escaping ([String: Any]) -> Void, completion: @escaping () -> Void = {}) {
        guard control == nil else { return }; controlBusy = true
        let task = JSONProcess(script: script, arguments: arguments, message: handler) { [weak self] in
            guard let self else { return }; self.control = nil; self.controlBusy = false; completion()
            if self.scanQueued { self.scanQueued = false; self.scan() }
        }
        control = task
        do { try task.start() } catch { control = nil; controlBusy = false; status = "本地工具启动失败，请重试。" }
    }
    func scan() {
        if control != nil { scanQueued = true; return }
        controlAction(script: "registry.py", arguments: ["scan"], handler: { [weak self] in self?.scanResult($0) })
    }
    func scanResult(_ object: [String: Any]) {
        guard let rows = object["devices"] as? [[String: Any]] else { if let text = object["message"] as? String { status = text }; return }
        devices = rows.compactMap { r in
            guard let id = r["id"] as? String, let name = r["name"] as? String else { return nil }
            return AndroidDevice(id:id,name:name,enabled:r["enabled"] as? Bool ?? true,online:r["online"] as? Bool ?? false,wireless:r["wireless"] as? Bool ?? false,pending:r["pending"] as? Bool ?? false)
        }
        needsRecovery = devices.contains(where: \.pending) && !active
        if active && !stopping {
            for device in devices where device.enabled && device.online && sessions[device.id] == nil { startDevice(device) }
        }
    }
    func enable(_ device: AndroidDevice, _ enabled: Bool) {
        guard !active else { return }
        controlAction(script: "registry.py", arguments: ["enable","--device-id",device.id,"--enabled",enabled ? "true":"false"], handler: { [weak self] in self?.scanResult($0) })
    }
    func toggle() { if active { stopMix() } else if needsRecovery { recover() } else { startMix() } }
    func startMix() {
        guard !active, !stopping, !controlBusy else { return }
        guard !needsRecovery else { status = "请先恢复上次的耳机设置。"; return }
        let available = devices.filter { $0.enabled && $0.online && $0.wireless }
        guard !available.isEmpty else { status = "没有可用的已授权无线安卓设备。请在设备上打开无线调试，允许此 Mac 后刷新。"; scan(); return }
        guard let output = Route.resolve(selected), Route.channels(output) > 1, let input = Route.builtInInput() else { status = "请先让 Mac 连接耳机。"; refreshOutputs(); return }
        do {
            let value = ["input":Route.uid(Route.current(true)),"output":Route.uid(Route.current()),"set_input":Route.uid(input),"set_output":selected]
            try JSONSerialization.data(withJSONObject:value).write(to:journal,options:.atomic)
            try Route.set(input,input:true); try Route.set(output)
            active = true; lastFailure = nil; ready.removeAll(); status = "正在开启混音…"
            for device in available { startDevice(device) }
        } catch { _ = restoreMac(); status = "声音设备尚未准备好。" }
    }
    func startDevice(_ device: AndroidDevice) {
        guard sessions[device.id] == nil else { return }
        messages[device.id] = "正在接入…"
        let headphone = outputs.first(where: { $0.id == selected })?.name ?? ""
        let args = ["run","--device-id",device.id,"--transport","wireless","--headphone",headphone,"--buffer",stable ? "200":"100","--watch-stdin"]
        let task = JSONProcess(script:"controller.py",arguments:args,message:{ [weak self] object in
            guard let self else { return }
            let kind = object["state"] as? String ?? "", text = object["message"] as? String ?? ""
            self.messages[device.id] = text
            if kind == "running" { self.ready.insert(device.id); self.status = "混音已开启。用完点击图标恢复普通使用。" }
            if kind == "reconnecting" || kind == "preparing" { self.ready.remove(device.id) }
            if kind == "restore_pending" { self.needsRecovery = true }
            if kind == "error" { self.lastFailure = device.name + "：" + text; self.status = self.lastFailure! }
        },ended:{ [weak self] in
            guard let self else { return }; self.sessions.removeValue(forKey:device.id); self.ready.remove(device.id)
            if self.sessions.isEmpty { self.finishStop() }
        })
        sessions[device.id] = task
        do { try task.start() } catch { sessions.removeValue(forKey:device.id); messages[device.id] = "启动失败"; if sessions.isEmpty { finishStop() } }
    }
    func stopMix() {
        guard !stopping else { return }
        stopping = true; status = "正在停止转发并恢复普通使用…"
        if sessions.isEmpty { finishStop(); return }
        sessions.values.forEach { $0.stop() }
    }
    func finishStop() {
        active = false; stopping = false; ready.removeAll()
        let mac = restoreMac()
        needsRecovery = pendingRecords() || !mac
        status = needsRecovery ? "转发已停止；请解锁并连接设备，再点恢复普通使用。" : "普通模式：耳机连接和 Mac 输入已恢复。" + (lastFailure.map { "\n" + $0 } ?? "")
        scan(); let done = afterStop; afterStop = nil; done?()
    }
    func pendingRecords() -> Bool {
        let all = (try? FileManager.default.subpathsOfDirectory(atPath:root.path)) ?? []
        return all.contains { $0.hasSuffix("phone-restore.json") }
    }
    @discardableResult func restoreMac() -> Bool {
        guard FileManager.default.fileExists(atPath:journal.path) else { return true }
        guard let data = try? Data(contentsOf:journal),let value = try? JSONSerialization.jsonObject(with:data) as? [String:String] else { return false }
        if Route.restore(value) { try? FileManager.default.removeItem(at:journal); return true }; return false
    }
    func recover() {
        guard !active, control == nil else { return }
        status = "正在恢复普通使用…"
        controlAction(script:"recover_all.py",arguments:[],handler:{ [weak self] object in self?.status = object["message"] as? String ?? "正在恢复…" },completion:{ [weak self] in
            guard let self else { return }; _ = self.restoreMac(); self.needsRecovery = self.pendingRecords(); if !self.needsRecovery { self.status = "普通模式：设置已恢复。" }; self.scan()
        })
    }
    func startRemote() {
        let task = JSONProcess(script:"remote_server.py",arguments:[],message:{ [weak self] object in
            guard let self, let event = object["event"] as? String else { return }
            if event == "ready",let port = object["port"] as? Int,let fingerprint = object["fingerprint"] as? String {
                self.remoteReady = true
                let service = NetService(domain:"local.",type:"_devicemix._tcp.",name:"Device Mixer",port:Int32(port))
                service.setTXTRecord(NetService.data(fromTXTRecord:["fp":Data(fingerprint.utf8)])); self.service = service; service.publish(); self.publish()
            } else if event == "command",let action = object["action"] as? String {
                if action == "start" { self.startMix() } else if action == "stop" { self.active ? self.stopMix() : self.recover() } else { self.scan() }
            } else if event == "pairing",let uri = object["uri"] as? String {
                self.pairingURI = uri
                if let id = self.pendingInstall {
                    self.pendingInstall = nil
                    self.controlAction(script:"install_remote.py",arguments:["--device-id",id,"--pair-uri",uri],handler:{ [weak self] in self?.status = $0["message"] as? String ?? "" })
                }
            } else if event == "paired" { self.pairingURI = ""; self.status = "手机遥控器已配对，可以在手机上开启和停止。" }
        },ended:{ [weak self] in self?.remoteReady = false })
        remote = task; try? task.start()
    }
    func installRemote() {
        guard !active, control == nil, remoteReady, let device = devices.first(where:{$0.online}) else { status = "请先恢复普通模式，并让安卓设备连接此 Mac。"; return }
        pendingInstall = device.id; remote?.send(["type":"pair","name":device.name]); status = "正在准备手机端配对…"
    }
    func showPairing() { remote?.send(["type":"pair","name":"Android"]); showWindow() }
    func showWindow() { mainWindow?.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps:true) }
    func watchDevices() {
        let task = Process(), pipe = Pipe(); watcherPipe = pipe
        task.executableURL = Bundle.main.resourceURL!.appendingPathComponent("adb"); task.arguments = ["track-devices","-l"]; task.standardOutput = pipe; task.standardError = FileHandle.nullDevice
        watcher = task
        do { try task.run() } catch { return }
        DispatchQueue.global().async { [weak self] in
            while true {
                let data = pipe.fileHandleForReading.availableData
                if data.isEmpty { break }
                DispatchQueue.main.asyncAfter(deadline:.now()+0.5) { self?.scan() }
            }
        }
    }
    func shutdownServices() { service?.stop(); remote?.closeInput(); if watcher?.isRunning == true { watcher?.terminate() } }
}

final class HideWindowDelegate: NSObject, NSWindowDelegate {
    func windowShouldClose(_ sender: NSWindow) -> Bool { sender.orderOut(nil); return false }
}
final class StatusBar: NSObject {
    weak var model: Model?
    let item = NSStatusBar.system.statusItem(withLength:NSStatusItem.variableLength)
    init(model: Model) {
        self.model = model; super.init()
        item.button?.target = self; item.button?.action = #selector(click)
        item.button?.sendAction(on:[.leftMouseUp,.rightMouseUp]); refresh()
    }
    func refresh() {
        guard let model else { return }
        item.button?.image = NSImage(systemSymbolName:model.active ? "waveform" : "headphones",accessibilityDescription:"设备混音")
        item.button?.title = model.active ? " 混音" : ""
        item.button?.toolTip = model.needsRecovery ? "点击恢复普通使用；右键打开面板" : model.active ? "点击停止混音并恢复普通使用" : "点击开启混音；右键打开控制面板"
    }
    @objc func click() {
        guard let model else { return }
        if NSApp.currentEvent?.type == .rightMouseUp, let event = NSApp.currentEvent, let button = item.button {
            let menu = NSMenu()
            for (title,selector) in [("打开控制面板",#selector(show)),("恢复普通使用",#selector(recover)),("刷新安卓设备",#selector(refreshDevices)),("退出设备混音",#selector(quit))] {
                let entry = NSMenuItem(title:title,action:selector,keyEquivalent:""); entry.target = self; menu.addItem(entry)
            }
            NSMenu.popUpContextMenu(menu,with:event,for:button)
        } else { model.toggle() }
    }
    @objc func show() { model?.showWindow() }
    @objc func recover() { model?.active == true ? model?.stopMix() : model?.recover() }
    @objc func refreshDevices() { model?.scan() }
    @objc func quit() { NSApp.terminate(nil) }
}

struct Content: View {
    @ObservedObject var model: Model
    var qr: NSImage? {
        guard !model.pairingURI.isEmpty,let filter = CIFilter(name:"CIQRCodeGenerator") else { return nil }
        filter.setValue(Data(model.pairingURI.utf8),forKey:"inputMessage"); filter.setValue("M",forKey:"inputCorrectionLevel")
        guard let output = filter.outputImage?.transformed(by:CGAffineTransform(scaleX:6,y:6)),let image = CIContext().createCGImage(output,from:output.extent) else { return nil }
        return NSImage(cgImage:image,size:NSSize(width:210,height:210))
    }
    var body: some View {
        VStack(alignment:.leading,spacing:16) {
            HStack {
                if let icon = NSImage(named:NSImage.Name("AppIcon")) { Image(nsImage:icon).resizable().frame(width:48,height:48) }
                VStack(alignment:.leading) { Text("设备混音").font(.title2.bold()); Text(model.needsRecovery && !model.active ? "设置待恢复" : model.active ? "混音模式" : "普通模式").foregroundStyle(model.active ? .teal : .secondary) }
                Spacer(); Text("Wi-Fi").foregroundStyle(.secondary)
            }
            Picker("耳机输出",selection:$model.selected) { ForEach(model.outputs) { Text($0.name).tag($0.id) } }.disabled(model.active)
            VStack(alignment:.leading,spacing:10) {
                ForEach(model.devices) { device in
                    VStack(alignment:.leading,spacing:3) {
                        Toggle(device.name,isOn:Binding(get:{model.devices.first(where:{$0.id == device.id})?.enabled ?? false},set:{model.enable(device,$0)})).disabled(model.active || model.controlBusy)
                        Text(model.messages[device.id] ?? (device.online ? "已授权，自动发现" : "当前未连接")).font(.caption).foregroundStyle(.secondary)
                    }
                }
                if model.devices.isEmpty { Text("新安卓设备在允许此 Mac 后会自动出现在这里。").foregroundStyle(.secondary) }
            }.padding(14).frame(maxWidth:.infinity,alignment:.leading).background(.quaternary.opacity(0.5),in:RoundedRectangle(cornerRadius:12))
            Text(model.status).font(.callout).fixedSize(horizontal:false,vertical:true).padding(12).frame(maxWidth:.infinity,alignment:.leading).background(.teal.opacity(0.08),in:RoundedRectangle(cornerRadius:10))
            HStack {
                Button(model.stopping ? "正在恢复…" : model.active ? "恢复普通使用" : model.needsRecovery ? "恢复普通使用" : "开启混音") { model.toggle() }.buttonStyle(.borderedProminent).tint(.teal).controlSize(.large).disabled(model.stopping || model.controlBusy)
                Spacer(); Button("刷新设备") { model.refreshOutputs(); model.scan() }.disabled(model.controlBusy)
            }
            Toggle("更稳模式",isOn:$model.stable).disabled(model.active)
            Divider()
            HStack { Button("安装并配对手机端") { model.installRemote() }.disabled(model.active || model.controlBusy || !model.remoteReady); Spacer(); Button("显示配对码") { model.showPairing() }.disabled(!model.remoteReady) }
            if let qr { HStack { Image(nsImage:qr).interpolation(.none).resizable().frame(width:180,height:180); VStack(alignment:.leading) { Text("配对码 3 分钟内有效"); Button("复制配对链接") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(model.pairingURI,forType:.string) }; Text("配对链接只交给自己的设备。").font(.caption).foregroundStyle(.secondary) } } }
            Text("左键点菜单栏耳机图标即可切换，右键打开面板。关闭窗口只是收起；退出会停止并尝试恢复。普通模式不转发音频。")
                .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true)
            Text("手机和 Mac 需在同一可互通网络，无线调试保持开启。开始和恢复设置时，请解锁设备。仅媒体播放；通话暂不支持。")
                .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true)
        }.padding(24).frame(width:500).onAppear { model.attachWindow() }
    }
}
final class Delegate: NSObject, NSApplicationDelegate {
    var model: Model?
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication) -> Bool { false }
    func confirmPending() -> Bool {
        let alert = NSAlert(); alert.messageText = "手机直连音频尚未恢复"; alert.informativeText = "转发已经停止。请先让手机无线连接可用并解锁，再恢复普通使用。也可以退出并保留恢复记录。"; alert.addButton(withTitle:"先恢复设置"); alert.addButton(withTitle:"仍然退出")
        return alert.runModal() == .alertSecondButtonReturn
    }
    func applicationShouldTerminate(_ sender:NSApplication) -> NSApplication.TerminateReply {
        guard let model else { return .terminateNow }
        if model.active || !model.sessions.isEmpty {
            model.afterStop = { [weak self,weak model] in
                guard let model else { sender.reply(toApplicationShouldTerminate:true); return }
                let quit = !model.needsRecovery || self?.confirmPending() == true
                if quit { model.shutdownServices() } else { model.recover(); model.showWindow() }
                sender.reply(toApplicationShouldTerminate:quit)
            }; model.stopMix(); return .terminateLater
        }
        if model.needsRecovery && !confirmPending() { model.recover(); model.showWindow(); return .terminateCancel }
        model.shutdownServices(); return .terminateNow
    }
}
@main struct DeviceMixer: App {
    @NSApplicationDelegateAdaptor(Delegate.self) var delegate
    @StateObject var model = Model()
    var body: some Scene {
        Window("设备混音",id:"main") { Content(model:model).onAppear { delegate.model = model } }
            .windowResizability(.contentSize).commands { CommandGroup(replacing:.newItem) {} }
    }
}
