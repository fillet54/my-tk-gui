import os
from PIL import Image, ImageFilter

for p in [path for path in os.listdir() if path.endswith('png')]:
    im = Image.open(p)
    resized_im = im.resize((round(im.size[0]*2), round(im.size[1]*2)), Image.BICUBIC)
    #resized_im.filter(ImageFilter.EDGE_ENHANCE)
    resized_im.filter(ImageFilter.SHARPEN)

    resized_im.save(os.path.join('hidpi', p))

