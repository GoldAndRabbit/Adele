"""Keep the original stage pixels outside the common foreground of source and oil."""
import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def person_mask(path, size):
    import Quartz
    import Vision
    from Foundation import NSURL

    request = Vision.VNGeneratePersonSegmentationRequest.alloc().initWithCompletionHandler_(None)
    request.setQualityLevel_(Vision.VNGeneratePersonSegmentationRequestQualityLevelAccurate)
    request.setOutputPixelFormat_(Quartz.kCVPixelFormatType_OneComponent8)
    handler = Vision.VNSequenceRequestHandler.new()
    ok, error = handler.performRequests_onImageURL_error_([request], NSURL.fileURLWithPath_(str(Path(path).resolve())), None)
    if not ok or not request.results():
        raise ValueError(f'Person mask unavailable for {path}: {error}')
    ci = Quartz.CIImage.imageWithCVPixelBuffer_(request.results()[0].pixelBuffer())
    context = Quartz.CIContext.contextWithOptions_(None)
    bitmap = Quartz.NSBitmapImageRep.alloc().initWithCGImage_(context.createCGImage_fromRect_(ci, ci.extent()))
    png = bitmap.representationUsingType_properties_(Quartz.NSBitmapImageFileTypePNG, {})
    with Image.open(io.BytesIO(bytes(png))) as mask:
        return np.asarray(mask.convert('L').resize(size, Image.Resampling.BILINEAR))


def on_original_stage(source, oil, base, output):
    """Transfer oil within shared subject pixels that also agree photometrically."""
    original = cv2.imread(str(source))
    painted = cv2.imread(str(oil))
    background = cv2.imread(str(base))
    height, width = original.shape[:2]
    size = (width, height)
    painted = cv2.resize(painted, size, interpolation=cv2.INTER_CUBIC)
    mask = np.minimum(person_mask(source, size), person_mask(oil, size))
    if np.count_nonzero(mask > 190) < .025*width*height:
        raise ValueError('Insufficient matching foreground. Use source color treatment.')
    # Suppress stray edge pixels and mismatched details before feathering.
    mask = cv2.erode(mask, np.ones((5, 5), np.uint8))
    a = cv2.cvtColor(original, cv2.COLOR_BGR2LAB).astype(np.float32)
    b = cv2.cvtColor(painted, cv2.COLOR_BGR2LAB).astype(np.float32)
    difference = cv2.GaussianBlur(np.mean(np.abs(a-b), axis=2), (0, 0), 3)
    opacity = cv2.GaussianBlur(mask, (0, 0), 2) / 255 * np.clip(1.2-difference/48, 0, 1)
    # Band-limited brush texture cannot introduce a second nose or eyelid when
    # the painted performer moves slightly. Keep all low-frequency shapes.
    luminance = cv2.cvtColor(painted, cv2.COLOR_BGR2GRAY).astype(np.float32)
    brush = luminance - cv2.GaussianBlur(luminance, (0, 0), .9)
    final = background + (opacity * np.clip(brush, -5, 5))[:, :, None]
    if not cv2.imwrite(str(output), final.clip(0, 255).astype('uint8')):
        raise OSError(f'Cannot save {output}')


def painted_subject(source, oil, background_path, output):
    """Keep whole painted subjects that occupy the original performer silhouettes."""
    base = cv2.imread(str(background_path))
    height, width = base.shape[:2]
    size = (width, height)
    painted = cv2.resize(cv2.imread(str(oil)), size, interpolation=cv2.INTER_CUBIC)
    src = person_mask(source, size)
    gen = person_mask(oil, size)
    source_binary = (src >= 110).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11,11))
    allowed = cv2.dilate(source_binary, kernel)
    count, labels, stats, _ = cv2.connectedComponentsWithStats((gen >= 100).astype(np.uint8))
    retained = np.zeros_like(src)
    for idx in range(1, count):
        component = labels == idx
        overlap = np.count_nonzero(component & (allowed > 0)) / stats[idx, cv2.CC_STAT_AREA]
        if overlap >= .77:
            retained[component] = gen[component]
    union = np.count_nonzero(source_binary | (retained > 100))
    match = np.count_nonzero(source_binary & (retained > 100)) / max(1, union)
    if match < .74:
        raise ValueError(f'Painted pose differs from source (mask overlap {match:.2f})')
    # Replace only the narrow fringe where the old and painted contours differ.
    # Never blend two different faces together.
    exposed = cv2.dilate(source_binary, kernel) & (retained < 180)
    if np.any(exposed):
        base = cv2.inpaint(base, np.uint8(exposed*255), 4, cv2.INPAINT_TELEA)
    alpha = cv2.GaussianBlur(retained, (3,3), .65).astype(np.float32)[:, :, None]/255
    final = painted*alpha + base*(1-alpha)
    if not cv2.imwrite(str(output), final.clip(0,255).astype(np.uint8)):
        raise OSError(f'Cannot save {output}')
