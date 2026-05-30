import cv2
import numpy as np
import os
import re

from config import (
    THRESHOLD_VALUE,
    LINE_HEIGHT,
    LINE_PADDING_Y,
    MIN_TEXT_PIXELS_PER_SLICE,
    STANZA_GAP_MULTIPLIER,
    DIVIDER_HEIGHT,
    DIVIDER_GAP,
    DIVIDER_MARGIN_X,
    FINAL_LEFT_CROP,
    FINAL_RIGHT_CROP,
    MIN_LINE_DISTANCE,
    DEBUG
)

def is_blank_page(image_path):
    
    gray = cv2.imread(
        image_path,
        cv2.IMREAD_GRAYSCALE
    )

    if gray is None:
        return False

    _, binary = cv2.threshold(
        gray,
        245,
        255,
        cv2.THRESH_BINARY_INV
    )

    num_labels, labels, stats, _ = (
        cv2.connectedComponentsWithStats(
            binary,
            connectivity=8
        )
    )

    large_components = 0

    for i in range(1, num_labels):

        area = stats[
            i,
            cv2.CC_STAT_AREA
        ]

        if area > 50:

            large_components += 1

    if DEBUG:

        print(
            f"{os.path.basename(image_path)} "
            f"large_components={large_components}"
        )

    return large_components < 1

def load_image(image_path):

    gray = cv2.imread(
        image_path,
        cv2.IMREAD_GRAYSCALE
    )

    if gray is None:

        raise Exception(
            f"Could not load image: {image_path}"
        )

    return gray

def binarize(gray):

    _, binary = cv2.threshold(
        gray,
        THRESHOLD_VALUE,
        255,
        cv2.THRESH_BINARY_INV
    )

    return binary

def crop_to_text(gray):

    binary = binarize(gray)

    coords = cv2.findNonZero(binary)

    if coords is None:
        return gray

    x, y, w, h = cv2.boundingRect(coords)

    padding = 12

    x = max(0, x - padding)
    y = max(0, y - padding)

    w = min(gray.shape[1] - x, w + padding * 2)
    h = min(gray.shape[0] - y, h + padding * 2)

    cropped = gray[y:y+h, x:x+w]

    return cropped


# GLOBAL PAGE DESKEW

def auto_deskew(gray):

    binary = binarize(gray)

    lines = cv2.HoughLinesP(
        binary,
        1,
        np.pi / 180,
        threshold=100,
        minLineLength=300,
        maxLineGap=30
    )

    if lines is None:
        return gray

    angles = []

    for line in lines:

        x1, y1, x2, y2 = line[0]

        angle = np.degrees(
            np.arctan2(
                y2 - y1,
                x2 - x1
            )
        )

        if -10 < angle < 10:

            angles.append(angle)

    if not angles:
        return gray

    median_angle = np.median(angles)

    (h, w) = gray.shape[:2]

    center = (w // 2, h // 2)

    matrix = cv2.getRotationMatrix2D(
        center,
        median_angle,
        1.0
    )

    rotated = cv2.warpAffine(
        gray,
        matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )
    if DEBUG:
        print(
            f"Deskew angle: {median_angle:.2f}"
        )

    return rotated


# LOCAL LINE DESKEW

def local_deskew_line(slice_img):

    binary = binarize(slice_img)

    lines = cv2.HoughLinesP(
        binary,
        1,
        np.pi / 180,
        threshold=30,
        minLineLength=100,
        maxLineGap=20
    )

    if lines is None:
        return slice_img

    angles = []

    for line in lines:

        x1, y1, x2, y2 = line[0]

        angle = np.degrees(
            np.arctan2(
                y2 - y1,
                x2 - x1
            )
        )

        if -6 < angle < 6:

            angles.append(angle)

    if not angles:
        return slice_img

    median_angle = np.median(angles)

    (h, w) = slice_img.shape[:2]

    center = (w // 2, h // 2)

    matrix = cv2.getRotationMatrix2D(
        center,
        median_angle,
        1.0
    )

    rotated = cv2.warpAffine(
        slice_img,
        matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )

    return rotated

# TRUE LINE DETECTION

def detect_text_lines(binary):

    horizontal_projection = np.sum(
        binary > 0,
        axis=1
    )

    threshold = np.max(horizontal_projection) * 0.10

    lines = []

    h = binary.shape[0]

    y = 0

    while y < h:

        while (
            y < h
            and horizontal_projection[y] < threshold
        ):
            y += 1

        if y >= h:
            break

        start_y = y

        while (
            y < h
            and horizontal_projection[y] >= threshold
        ):
            y += 1

        end_y = y

        region_height = end_y - start_y

        if region_height < 6:
            continue

        center_y = (
            start_y + end_y
        ) // 2

        y1 = center_y - (LINE_HEIGHT // 2)
        y2 = center_y + (LINE_HEIGHT // 2)

        y1 = max(0, y1)
        y2 = min(h, y2)

        band = binary[
            y1:y2,
            :
        ]

        text_pixels = np.sum(
            band > 0
        )

        if text_pixels < MIN_TEXT_PIXELS_PER_SLICE:
            continue

        should_add = True

        if lines:

            prev_y1, prev_y2 = lines[-1]

            overlap = (
                min(y2, prev_y2)
                - max(y1, prev_y1)
            )

            overlap_ratio = overlap / LINE_HEIGHT

            if overlap_ratio > 0.30:

                should_add = False

        if should_add:

            lines.append(
                (y1, y2)
            )

        y += MIN_LINE_DISTANCE

    return lines

def save_slice_image(
    slice_img,
    output_dir,
    base_name,
    slice_index
):

    slices_root = os.path.join(
        output_dir,
        "slices"
    )

    os.makedirs(
        slices_root,
        exist_ok=True
    )

    image_slice_folder = os.path.join(
        slices_root,
        base_name
    )

    os.makedirs(
        image_slice_folder,
        exist_ok=True
    )

    slice_filename = (
        f"{base_name}_slice_{slice_index:03d}.png"
    )

    slice_path = os.path.join(
        image_slice_folder,
        slice_filename
    )

    cv2.imwrite(
        slice_path,
        slice_img
    )

    return slice_path

def build_combined_ocr_page(
    slices,
    output_dir,
    base_name
):

    slice_images = []

    max_width = 0

    total_height = 0

    for s in slices:

        img = cv2.imread(
            s["slice_path"],
            cv2.IMREAD_GRAYSCALE
        )

        if img is None:
            continue

        slice_images.append(img)

        h, w = img.shape

        max_width = max(
            max_width,
            w
        )

        total_height += (
            h
            + DIVIDER_GAP
            + DIVIDER_HEIGHT
            + DIVIDER_GAP
        )

    if not slice_images:

        raise Exception(
            "No slice images found"
        )

    canvas = np.ones(
        (
            total_height,
            max_width
        ),
        dtype=np.uint8
    ) * 255

    current_y = 0

    for img in slice_images:

        h, w = img.shape

        x = (
            max_width - w
        ) // 2

        canvas[
            current_y:current_y+h,
            x:x+w
        ] = img

        current_y += h

        current_y += DIVIDER_GAP

        cv2.rectangle(

            canvas,

            (
                DIVIDER_MARGIN_X,
                current_y
            ),

            (
                max_width - DIVIDER_MARGIN_X,
                current_y + DIVIDER_HEIGHT
            ),

            0,

            -1
        )

        current_y += DIVIDER_HEIGHT

        current_y += DIVIDER_GAP

    combined_dir = os.path.join(
        output_dir,
        "combined_pages"
    )

    os.makedirs(
        combined_dir,
        exist_ok=True
    )

    combined_path = os.path.join(
        combined_dir,
        f"{base_name}_combined.png"
    )

# FINAL LEFT/RIGHT CROP

    canvas = canvas[
        :,
        FINAL_LEFT_CROP:
        canvas.shape[1] - FINAL_RIGHT_CROP
    ]

    cv2.imwrite(
        combined_path,
        canvas
    )

    return combined_path

def extract_line_slices(
    image_path,
    output_dir=None
):

    gray = load_image(image_path)

    cropped = crop_to_text(gray)

    cropped = auto_deskew(cropped)

    base_name = os.path.splitext(
        os.path.basename(image_path)
    )[0]

    if output_dir:

        crop_dir = os.path.join(
            output_dir,
            "cropped_pages"
        )

        os.makedirs(
            crop_dir,
            exist_ok=True
        )

        crop_path = os.path.join(
            crop_dir,
            f"{base_name}_cropped.png"
        )

        cv2.imwrite(
            crop_path,
            cropped
        )

    binary = binarize(cropped)

    lines = detect_text_lines(binary)

    line_data = []

    debug_img = cv2.cvtColor(
        cropped,
        cv2.COLOR_GRAY2BGR
    )

    for idx, (y1, y2) in enumerate(lines):

        top = max(
            0,
            y1 - LINE_PADDING_Y
        )

        bottom = min(
            cropped.shape[0],
            y2 + LINE_PADDING_Y
        )

        slice_img = cropped[
            top:bottom,
            :
        ]

        slice_img = local_deskew_line(
            slice_img
        )

        slice_path = save_slice_image(
            slice_img,
            output_dir,
            base_name,
            idx + 1
        )

        cv2.rectangle(
            debug_img,
            (0, top),
            (cropped.shape[1], bottom),
            (0, 0, 255),
            2
        )

        if DEBUG:
            print(
                f"Saved slice: {slice_path}"
            )

        line_data.append({

            "index": idx,

            "y1": y1,

            "y2": y2,

            "slice_path": slice_path
        })

    if output_dir:

        debug_dir = os.path.join(
            output_dir,
            "debug_lines"
        )

        os.makedirs(
            debug_dir,
            exist_ok=True
        )

        debug_path = os.path.join(
            debug_dir,
            f"{base_name}_debug.png"
        )
        if DEBUG:
            cv2.imwrite(
                debug_path,
                debug_img
            )

    return line_data

# OCR GARBAGE DETECTOR

def is_garbage_line(line):

    line = line.strip()

    if not line:
        return True

    # single english letter
    if re.fullmatch(
        r'[A-Za-z]',
        line
    ):
        return True

    # tiny numbers
    if re.fullmatch(
        r'\d{1,2}',
        line
    ):
        return True

    # random OCR symbol line
    if len(line) <= 2:

        if not re.search(
            r'[\u0900-\u097F]',
            line
        ):
            return True

    return False

# OCR WHOLE REBUILT PAGE

def ocr_line_slices(
    image_path,
    google_ocr_function,
    output_dir=None
):

    slices = extract_line_slices(
        image_path,
        output_dir
    )

    base_name = os.path.splitext(
        os.path.basename(image_path)
    )[0]

    combined_page_path = build_combined_ocr_page(
        slices,
        output_dir,
        base_name
    )

    full_text = google_ocr_function(
        combined_page_path
    )

    full_text = full_text.replace(
        "﻿________________",
        ""
    )

    lines = []

    page_number = None

    for line in full_text.splitlines():

        line = line.strip()

        if not line:
            continue

        if is_garbage_line(line):
            continue

        # keep only real page number
        if re.fullmatch(
            r'\d{3,4}',
            line
        ):

            page_number = line
            continue

        if (
            "____" in line
            or "——" in line
            or "===" in line
        ):
            continue

        line = re.sub(
            r'\s+',
            ' ',
            line
        )

        line = line.strip()

        if line:

            lines.append(line)

    merged_lines = []

    for line in lines:

        if not merged_lines:

            merged_lines.append(line)
            continue

        prev = merged_lines[-1]

        if len(prev.split()) <= 2:

            merged_lines[-1] = (
                prev + " " + line
            )

        else:

            merged_lines.append(line)

    final_text = "\n".join(
        merged_lines
    )

    if page_number:
    
        final_text += (
            "\n\n" +
            page_number
        )

    if output_dir:

        txt_path = os.path.join(
            output_dir,
            f"{base_name}.txt"
        )

        with open(
            txt_path,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(final_text)

    return final_text

# PROCESS ENTIRE FOLDER

def process_image_folder(
    folder_path,
    google_ocr_function,
    output_txt_path,
    output_dir=None
):

    supported = (
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".webp"
    )

    image_files = sorted([

        f for f in os.listdir(folder_path)

        if f.lower().endswith(supported)

    ])

    with open(
        output_txt_path,
        "w",
        encoding="utf-8"
    ) as out_file:

        for img_name in image_files:

            image_path = os.path.join(
                folder_path,
                img_name
            )

            print(
                f"Processing: {img_name}"
            )

            try:

                page_text = ocr_line_slices(
                    image_path,
                    google_ocr_function,
                    output_dir
                )

                out_file.write(
                    page_text
                )

                out_file.write(
                    "\n\n"
                )

            except Exception as e:

                print(
                    f"FAILED: {img_name}"
                )

                print(str(e))

    print("DONE.")