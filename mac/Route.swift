import Foundation
import CoreAudio

struct OutputDevice: Identifiable, Hashable { let id: String; let name: String }
enum MixError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let s) = self { return s }; return nil }
}
enum Route {
    static let system = AudioObjectID(kAudioObjectSystemObject)
    static func address(_ selector: AudioObjectPropertySelector, _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> AudioObjectPropertyAddress {
        AudioObjectPropertyAddress(mSelector: selector, mScope: scope, mElement: kAudioObjectPropertyElementMain)
    }
    static func scalar<T>(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector, _ initial: T) -> T {
        var value = initial, size = UInt32(MemoryLayout<T>.size), a = address(selector)
        _ = withUnsafeMutableBytes(of: &value) { AudioObjectGetPropertyData(object, &a, 0, nil, &size, $0.baseAddress!) }
        return value
    }
    static func string(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String {
        var value: Unmanaged<CFString>?, a = address(selector), size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        let status = withUnsafeMutablePointer(to: &value) { AudioObjectGetPropertyData(object, &a, 0, nil, &size, $0) }
        return status == noErr ? (value?.takeRetainedValue() as String? ?? "") : ""
    }
    static func devices() -> [AudioObjectID] {
        var a = address(kAudioHardwarePropertyDevices), size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(system, &a, 0, nil, &size) == noErr, size > 0 else { return [] }
        var result = [AudioObjectID](repeating: 0, count: Int(size)/4)
        let status = result.withUnsafeMutableBytes { AudioObjectGetPropertyData(system, &a, 0, nil, &size, $0.baseAddress!) }
        return status == noErr ? result : []
    }
    static func channels(_ object: AudioObjectID, input: Bool = false) -> UInt32 {
        var a = address(kAudioDevicePropertyStreamConfiguration, input ? kAudioObjectPropertyScopeInput : kAudioObjectPropertyScopeOutput), size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(object, &a, 0, nil, &size) == noErr, size > 0 else { return 0 }
        let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { raw.deallocate() }
        guard AudioObjectGetPropertyData(object, &a, 0, nil, &size, raw) == noErr else { return 0 }
        return UnsafeMutableAudioBufferListPointer(raw.assumingMemoryBound(to: AudioBufferList.self)).reduce(0) { $0 + $1.mNumberChannels }
    }
    static func current(_ input: Bool = false) -> AudioObjectID {
        scalar(system, input ? kAudioHardwarePropertyDefaultInputDevice : kAudioHardwarePropertyDefaultOutputDevice, AudioObjectID(0))
    }
    static func uid(_ id: AudioObjectID) -> String { string(id, kAudioDevicePropertyDeviceUID) }
    static func resolve(_ uid: String, input: Bool = false) -> AudioObjectID? { devices().first { self.uid($0) == uid && channels($0, input: input) > 0 } }
    static func outputs() -> [OutputDevice] { devices().filter { channels($0) > 1 }.map { OutputDevice(id: uid($0), name: string($0, kAudioObjectPropertyName)) } }
    static func builtInInput() -> AudioObjectID? { devices().first { channels($0, input: true) > 0 && scalar($0, kAudioDevicePropertyTransportType, UInt32(0)) == kAudioDeviceTransportTypeBuiltIn } }
    static func set(_ device: AudioObjectID, input: Bool = false) throws {
        var value = device, a = address(input ? kAudioHardwarePropertyDefaultInputDevice : kAudioHardwarePropertyDefaultOutputDevice)
        guard AudioObjectSetPropertyData(system, &a, 0, nil, 4, &value) == noErr else { throw MixError.message("声音设备切换未完成。") }
    }
    static func restore(_ record: [String: String]) -> Bool {
        var success = true
        for input in [true, false] {
            let key = input ? "input" : "output", active = uid(current(input))
            guard active == record["set_" + key], active != record[key] else { continue }
            guard let previous = record[key], let id = resolve(previous, input: input) else { success = false; continue }
            do { try set(id, input: input) } catch { success = false }
        }
        return success
    }
}
