import Foundation
import AppKit
import Vision
import ImageIO

do {
    guard CommandLine.arguments.count == 2,
          let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: CommandLine.arguments[1]) as CFURL, nil),
          let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [String: Any],
          let originalWidth = props[kCGImagePropertyPixelWidth as String] as? Int,
          let originalHeight = props[kCGImagePropertyPixelHeight as String] as? Int,
          let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceThumbnailMaxPixelSize: 1200] as CFDictionary)
    else { exit(1) }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .fast
    request.usesCPUOnly = true
    request.recognitionLanguages = ["en-US"]
    try VNImageRequestHandler(cgImage: image).perform([request])
    let bitmap = NSBitmapImageRep(cgImage: image)
    var texts: [[String: Any]] = []
    for observation in request.results ?? [] {
        guard let text = observation.topCandidates(1).first?.string else { continue }
        var row: [String: Any] = ["text": text, "y": (1-observation.boundingBox.midY)*Double(originalHeight), "x": observation.boundingBox.midX*Double(originalWidth)]
        if ["媒体音频", "Media audio"].contains(text.trimmingCharacters(in: .whitespaces)) {
            let x = Int(Double(image.width)*0.87), y = Int((1-observation.boundingBox.midY)*Double(image.height)), radius = max(4,image.width/65)
            var blue = 0, total = 0
            for sy in max(0,y-radius)..<min(image.height,y+radius) {
                for sx in max(0,x-radius*2)..<min(image.width,x+radius*2) {
                    if let c = bitmap.colorAt(x: sx, y: sy)?.usingColorSpace(.deviceRGB) {
                        if c.blueComponent > c.redComponent+0.14 && c.blueComponent > 0.43 && c.greenComponent > c.redComponent+0.06 { blue += 1 }
                        total += 1
                    }
                }
            }
            let fraction = Double(blue)/Double(max(1,total))
            if fraction > 0.12 { row["switch"] = true } else if fraction < 0.02 { row["switch"] = false }
        }
        texts.append(row)
    }
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: ["width": originalWidth,"height":originalHeight,"texts":texts]))
} catch { exit(1) }
