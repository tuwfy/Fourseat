from PIL import Image, ImageDraw

def draw_logo(size, filename, color="#815429"):
    # Create a transparent image (antialiasing by drawing large and resizing)
    large_size = size * 4
    img = Image.new("RGBA", (large_size, large_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    line_width = max(2, int(large_size * 0.07))
    margin = line_width
    
    # Bounding box for the circle
    box = [margin, margin, large_size - margin, large_size - margin]
    
    # Draw the circle
    draw.ellipse(box, outline=color, width=line_width)
    
    # Center coordinates
    cx = large_size // 2
    cy = large_size // 2
    
    # Draw the vertical line
    draw.line([(cx, margin), (cx, large_size - margin)], fill=color, width=line_width)
    
    # Draw the horizontal line
    draw.line([(margin, cy), (large_size - margin, cy)], fill=color, width=line_width)
    
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    img.save(filename)

draw_logo(512, "logo-circle.png")
draw_logo(32, "favicon-32.png")
draw_logo(180, "favicon-180.png")
draw_logo(192, "icon-192.png")
draw_logo(512, "icon-512.png")

print("Logos generated.")
