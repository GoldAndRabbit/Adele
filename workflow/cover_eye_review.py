"""Flag reference images for visual eye review on macOS using Apple Vision."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def eye_aperture(eye):
    """Lid opening divided by eye width, independent of head roll."""
    if not eye or eye.pointCount() < 4:
        return None
    points = np.array([(p.x, p.y) for p in eye.normalizedPoints()[:eye.pointCount()]])
    offsets = points[:, None] - points[None, :]
    distances = (offsets ** 2).sum(axis=2)
    i, j = np.unravel_index(distances.argmax(), distances.shape)
    width_squared = distances[i, j]
    if not width_squared:
        return None
    dx, dy = offsets[i, j]
    return float(np.ptp(points @ np.array([-dy, dx])) / width_squared)


def inspect_eyes(path):
    """Report measured landmarks. Profiles, glasses and small faces require visual review."""
    import Vision
    from Foundation import NSURL

    url = NSURL.fileURLWithPath_(str(path.resolve()))
    request = Vision.VNDetectFaceLandmarksRequest.new()
    request.setRevision_(Vision.VNDetectFaceLandmarksRequestRevision3)
    ok, error = Vision.VNSequenceRequestHandler.new().performRequests_onImageURL_error_([request], url, None)
    if not ok:
        raise RuntimeError(str(error))
    faces = []
    for face in request.results() or []:
        landmarks = face.landmarks()
        if not landmarks:
            continue
        left = eye_aperture(landmarks.leftEye())
        right = eye_aperture(landmarks.rightEye())
        bounds = face.boundingBox()
        width = bounds.size.width
        faces.append({"x": bounds.origin.x, "y": 1 - bounds.origin.y - bounds.size.height,
                      "width": width, "height": bounds.size.height,
                      "left_eye": left, "right_eye": right,
                      "check_closed": left is not None and right is not None
                                      and width > .055 and max(left, right) < .14})
    return sorted(faces, key=lambda f: f["width"], reverse=True)


def check_for_blink(image, spec, role):
    """Hold a suspected blink for visual review before spending GPU time or publishing."""
    faces = inspect_eyes(image)
    anchor = spec.get("lead_face_x")
    if anchor is not None:
        # The reviewer marks the named lead in the original shot. Face size alone
        # cannot distinguish a guest from the billed artist.
        matching = [f for f in faces if f["x"] <= anchor <= f["x"] + f["width"]]
        if len(matching) != 1:
            raise ValueError(f"{role} 无法在标记位置确认主唱，请复查：{image}")
        lead = matching[0]
        if any(f["width"] >= lead["width"] for f in faces if f is not lead):
            raise ValueError(f"{role} 其他人物与主唱同大或更大，请重选：{image}")
    reviewed = spec.get("eye_review", {}).get(role, {})
    if reviewed.get("reason") and reviewed.get("sha256") == hashlib.sha256(image.read_bytes()).hexdigest():
        return
    if any(face["check_closed"] for face in faces):
        raise ValueError(f"{role} 疑似闭眼，需放大核对双眼或重选本曲原帧：{image}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="+", type=Path)
    for image in parser.parse_args().image:
        print(json.dumps({"file": str(image), "faces": inspect_eyes(image)}, ensure_ascii=False))
