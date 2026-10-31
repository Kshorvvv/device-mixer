import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

let folder = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
func draw(_ size:Int,_ destination:URL) throws {
    let space = CGColorSpaceCreateDeviceRGB()
    let c = CGContext(data:nil,width:size,height:size,bitsPerComponent:8,bytesPerRow:0,space:space,bitmapInfo:CGImageAlphaInfo.premultipliedLast.rawValue)!
    c.scaleBy(x:CGFloat(size)/1024,y:CGFloat(size)/1024)
    c.translateBy(x:0,y:1024);c.scaleBy(x:1,y:-1)
    let square = CGPath(roundedRect:CGRect(x:64,y:64,width:896,height:896),cornerWidth:210,cornerHeight:210,transform:nil)
    c.saveGState();c.setShadow(offset:CGSize(width:0,height:16),blur:28,color:CGColor(gray:0,alpha:0.16));c.addPath(square);c.setFillColor(CGColor(red:0.06,green:0.65,blue:0.7,alpha:1));c.fillPath();c.restoreGState()
    c.saveGState();c.addPath(square);c.clip()
    let colors = [CGColor(red:0.03,green:0.76,blue:0.65,alpha:1),CGColor(red:0.13,green:0.34,blue:0.9,alpha:1)] as CFArray
    c.drawLinearGradient(CGGradient(colorsSpace:space,colors:colors,locations:[0,1])!,start:CGPoint(x:120,y:140),end:CGPoint(x:900,y:920),options:[]);c.restoreGState()
    c.setStrokeColor(CGColor(gray:1,alpha:1));c.setLineWidth(64);c.setLineCap(.round)
    c.move(to:CGPoint(x:280,y:586));c.addLine(to:CGPoint(x:280,y:462));c.addCurve(to:CGPoint(x:744,y:462),control1:CGPoint(x:280,y:176),control2:CGPoint(x:744,y:176));c.addLine(to:CGPoint(x:744,y:586));c.strokePath()
    c.setFillColor(CGColor(gray:1,alpha:1))
    c.addPath(CGPath(roundedRect:CGRect(x:214,y:500,width:132,height:236),cornerWidth:54,cornerHeight:54,transform:nil));c.fillPath()
    c.addPath(CGPath(roundedRect:CGRect(x:678,y:500,width:132,height:236),cornerWidth:54,cornerHeight:54,transform:nil));c.fillPath()
    c.setLineWidth(32);c.setStrokeColor(CGColor(red:1,green:0.83,blue:0.37,alpha:1))
    c.move(to:CGPoint(x:412,y:610));c.addCurve(to:CGPoint(x:512,y:610),control1:CGPoint(x:452,y:478),control2:CGPoint(x:472,y:742));c.addCurve(to:CGPoint(x:612,y:610),control1:CGPoint(x:552,y:478),control2:CGPoint(x:572,y:742));c.strokePath()
    let image = c.makeImage()!
    let d = CGImageDestinationCreateWithURL(destination as CFURL,UTType.png.identifier as CFString,1,nil)!
    CGImageDestinationAddImage(d,image,nil);CGImageDestinationFinalize(d)
}
try draw(1024,folder.appendingPathComponent("icon-1024.png"))
try draw(192,folder.appendingPathComponent("icon-192.png"))
let iconset = folder.appendingPathComponent("AppIcon.iconset")
try FileManager.default.createDirectory(at:iconset,withIntermediateDirectories:true)
for n in [16,32,128,256,512] {
    try draw(n,iconset.appendingPathComponent("icon_\(n)x\(n).png"))
    try draw(n*2,iconset.appendingPathComponent("icon_\(n)x\(n)@2x.png"))
}
