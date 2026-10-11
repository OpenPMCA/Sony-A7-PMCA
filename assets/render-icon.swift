// CoreGraphics export of the geometry in the user-selected SVG. No window is opened.
import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

let root = URL(fileURLWithPath: CommandLine.arguments[1])
let iconset = root.appendingPathComponent("build/sony-open-pmca.iconset")
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
let space = CGColorSpace(name: CGColorSpace.sRGB)!
func color(_ hex: UInt32) -> CGColor {
    CGColor(colorSpace: space, components: [CGFloat((hex >> 16) & 255)/255,
            CGFloat((hex >> 8) & 255)/255, CGFloat(hex & 255)/255, 1])!
}
func render(_ size: Int, _ output: URL) {
    let ctx = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8,
                        bytesPerRow: size*4, space: space,
                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    ctx.translateBy(x: 0, y: CGFloat(size))
    ctx.scaleBy(x: CGFloat(size)/128, y: -CGFloat(size)/128)
    func circle(_ radius: CGFloat, _ fill: UInt32, _ stroke: UInt32? = nil, _ width: CGFloat = 1) {
        ctx.addEllipse(in: CGRect(x: 64-radius, y: 64-radius, width: radius*2, height: radius*2))
        ctx.setFillColor(color(fill))
        if let stroke {
            ctx.setStrokeColor(color(stroke)); ctx.setLineWidth(width); ctx.drawPath(using: .fillStroke)
        } else { ctx.fillPath() }
    }
    ctx.setLineDash(phase: 0, lengths: [4,2])
    circle(58, 0x1B1C20, 0x50545C, 3)
    ctx.setLineDash(phase: 0, lengths: [])
    circle(48, 0x101114, 0xF56024, 5)
    circle(40, 0x090A0C)
    ctx.setStrokeColor(color(0xFFFFFF)); ctx.setLineWidth(6)
    ctx.setLineCap(.round); ctx.setLineJoin(.round)
    ctx.move(to: CGPoint(x:48,y:76))
    ctx.addCurve(to: CGPoint(x:52,y:46), control1: CGPoint(x:42,y:68), control2: CGPoint(x:42,y:54))
    ctx.addCurve(to: CGPoint(x:78,y:52), control1: CGPoint(x:62,y:38), control2: CGPoint(x:74,y:42))
    ctx.addCurve(to: CGPoint(x:94,y:82), control1: CGPoint(x:84,y:64), control2: CGPoint(x:88,y:78))
    ctx.strokePath()
    ctx.move(to: CGPoint(x:52,y:46))
    ctx.addCurve(to: CGPoint(x:54,y:74), control1: CGPoint(x:44,y:54), control2: CGPoint(x:44,y:68))
    ctx.addCurve(to: CGPoint(x:82,y:56), control1: CGPoint(x:66,y:80), control2: CGPoint(x:82,y:56))
    ctx.strokePath()
    ctx.setFillColor(color(0xFFFFFF))
    ctx.fillEllipse(in: CGRect(x:60.8,y:8.8,width:6.4,height:6.4))
    let dest = CGImageDestinationCreateWithURL(output as CFURL, UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(dest, ctx.makeImage()!, nil)
    precondition(CGImageDestinationFinalize(dest), "Cannot write icon")
}
render(1024, root.appendingPathComponent("assets/sony-open-pmca.png"))
for size in [16,32,128,256,512] {
    render(size, iconset.appendingPathComponent("icon_\(size)x\(size).png"))
    render(size*2, iconset.appendingPathComponent("icon_\(size)x\(size)@2x.png"))
}
