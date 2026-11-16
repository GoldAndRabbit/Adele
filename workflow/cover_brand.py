"""Verify both rasterized brand assets together at the cover's fixed top-left anchor."""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]

BRAND_LAYOUT = "adele-top-left-v1"
BRAND_X = 60
BRAND_Y = 34
BRAND_GAP = 10
LANDSCAPE_LOGO_FRACTION = .17
PORTRAIT_LOGO_FRACTION = .18
BADGE_WIDTH_FRACTION = .231 / .284


def portrait_logo_width(width):
    return round(width * PORTRAIT_LOGO_FRACTION)


def landscape_logo_width(width):
    """Use the approved landscape width fraction."""
    return round(width * LANDSCAPE_LOGO_FRACTION)


@lru_cache(maxsize=1)
def _assets():
    with Image.open(ROOT/'assets/adele-logo.png') as image:
        alpha = image.getchannel('A').copy()
    badge = cv2.imread(str(ROOT/'assets/4K60-logo.jpg'), cv2.IMREAD_GRAYSCALE)
    return alpha, badge


def has_left_brand(image, *, expected_width=None):
    """Find the gold badge and check its white wordmark at the matching size."""
    alpha, badge = _assets()
    if expected_width is None:
        expected_width = (portrait_logo_width(image.width) if image.width < image.height
                          else landscape_logo_width(image.width))
    region_width, region_height = 475, 380
    if expected_width:
        badge_width = round(expected_width * BADGE_WIDTH_FRACTION)
        region_width = BRAND_X + expected_width
        region_height = (BRAND_Y + int(alpha.height * expected_width / alpha.width) + BRAND_GAP
                         + int(badge_width * badge.shape[0] / badge.shape[1]))
    region = np.array(image.crop((0, 0, min(region_width, image.width), min(region_height, image.height))).convert('RGB'))
    gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
    icon = cv2.resize(badge, (32, 24), interpolation=cv2.INTER_AREA)[2:-2,2:-2]
    # Validate the approved size at the fixed anchor.
    widths = [expected_width]
    for lw in widths:
        w = round(lw * BADGE_WIDTH_FRACTION)
        h = int(w*badge.shape[0]/badge.shape[1])
        lh = int(alpha.height*lw/alpha.width)
        x, y = BRAND_X+(lw-w)//2, BRAND_Y+lh+10
        patch = gray[y:y+h,x:x+w]
        if patch.shape != (h,w):
            continue
        small = cv2.resize(patch,(32,24),interpolation=cv2.INTER_AREA)[2:-2,2:-2]
        if cv2.matchTemplate(small,icon,cv2.TM_CCOEFF_NORMED)[0,0] < .94:
            continue
        ink,ring = _glyph_masks(lw,lh)
        glyph = gray[BRAND_Y:BRAND_Y+lh,BRAND_X:BRAND_X+lw]
        if glyph.shape == ink.shape and glyph[ink].mean()>202 and glyph[ink].mean()-glyph[ring].mean()>25:
            return True
    return False


@lru_cache(maxsize=128)
def _glyph_masks(width,height):
    alpha,_ = _assets()
    glyph = np.asarray(alpha.resize((width,height),Image.Resampling.LANCZOS))
    ink = glyph>210
    ring = (cv2.dilate(ink.astype(np.uint8),np.ones((5,5),np.uint8))>0)&(glyph<35)
    return ink,ring
