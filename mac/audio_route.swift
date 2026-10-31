import Foundation
import CoreAudio

let sys = AudioObjectID(kAudioObjectSystemObject)
func address(_ selector: AudioObjectPropertySelector, _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: selector, mScope: scope, mElement: kAudioObjectPropertyElementMain)
}
func scalar<T>(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector, _ initial: T, scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> T {
    var value = initial, size = UInt32(MemoryLayout<T>.size), a = address(selector, scope)
    _ = withUnsafeMutableBytes(of: &value) { AudioObjectGetPropertyData(object, &a, 0, nil, &size, $0.baseAddress!) }
    return value
}
func ids(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector, scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> [AudioObjectID] {
    var a = address(selector, scope), size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(object, &a, 0, nil, &size) == noErr else { return [] }
    var values = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    let status = values.withUnsafeMutableBytes { AudioObjectGetPropertyData(object, &a, 0, nil, &size, $0.baseAddress!) }
    return status == noErr ? values : []
}
func name(_ object: AudioObjectID) -> String {
    var a = address(kAudioObjectPropertyName), value: Unmanaged<CFString>? = nil
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    let result = withUnsafeMutablePointer(to: &value) { AudioObjectGetPropertyData(object, &a, 0, nil, &size, $0) }
    guard result == noErr, let value else { return "" }
    return value.takeRetainedValue() as String
}
func channels(_ object: AudioObjectID, _ scope: AudioObjectPropertyScope) -> UInt32 {
    var a = address(kAudioDevicePropertyStreamConfiguration, scope), size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(object, &a, 0, nil, &size) == noErr, size > 0 else { return 0 }
    let p = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: MemoryLayout<AudioBufferList>.alignment)
    defer { p.deallocate() }
    guard AudioObjectGetPropertyData(object, &a, 0, nil, &size, p) == noErr else { return 0 }
    return UnsafeMutableAudioBufferListPointer(p.assumingMemoryBound(to: AudioBufferList.self)).reduce(0) { $0 + $1.mNumberChannels }
}
let args = Array(CommandLine.arguments.dropFirst())
if args.count == 2 && ["set-input", "set-output"].contains(args[0]) {
    let scope = args[0] == "set-input" ? kAudioObjectPropertyScopeInput : kAudioObjectPropertyScopeOutput
    let selector = args[0] == "set-input" ? kAudioHardwarePropertyDefaultInputDevice : kAudioHardwarePropertyDefaultOutputDevice
    let matches = ids(sys, kAudioHardwarePropertyDevices).filter { name($0) == args[1] && channels($0, scope) > 0 }
    guard matches.count == 1 else { print("匹配的声音设备不是一个：\(matches.count)"); exit(2) }
    var value = matches[0], a = address(selector)
    let result = AudioObjectSetPropertyData(sys, &a, 0, nil, UInt32(MemoryLayout<AudioObjectID>.size), &value)
    guard result == noErr else { print("声音路由设置失败：\(result)"); exit(3) }
}
let defaultInput = scalar(sys, kAudioHardwarePropertyDefaultInputDevice, AudioObjectID(0))
let defaultOutput = scalar(sys, kAudioHardwarePropertyDefaultOutputDevice, AudioObjectID(0))
var devices: [[String: Any]] = []
for d in ids(sys, kAudioHardwarePropertyDevices) {
    devices.append(["id": d, "name": name(d), "input_channels": channels(d, kAudioObjectPropertyScopeInput), "output_channels": channels(d, kAudioObjectPropertyScopeOutput), "sample_rate": scalar(d, kAudioDevicePropertyNominalSampleRate, Double(0)), "default_input": d == defaultInput, "default_output": d == defaultOutput, "running": scalar(d, kAudioDevicePropertyDeviceIsRunningSomewhere, UInt32(0)) == 1])
}
var processes: [[String: Any]] = []
if args.first == "processes" {
    let allowed = Set(args.dropFirst().compactMap { Int32($0) })
    for p in ids(sys, kAudioHardwarePropertyProcessObjectList) {
        let pid = scalar(p, kAudioProcessPropertyPID, Int32(0))
        if allowed.contains(pid) {
            processes.append(["pid": pid, "output_running": scalar(p, kAudioProcessPropertyIsRunningOutput, UInt32(0)) == 1, "input_running": scalar(p, kAudioProcessPropertyIsRunningInput, UInt32(0)) == 1, "devices": ids(p, kAudioProcessPropertyDevices, scope: kAudioObjectPropertyScopeOutput).map { ["id": $0, "name": name($0)] }])
        }
    }
}
let result: [String: Any] = ["default_input": name(defaultInput), "default_output": name(defaultOutput), "devices": devices, "processes": processes]
let data = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
print(String(data: data, encoding: .utf8)!)
