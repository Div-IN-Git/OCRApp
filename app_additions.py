import os
import re

# ============================================================
# INPUT FOLDER
# ============================================================

FOLDER = r"D:\compressed\222out"

# ============================================================
# FIND TXT FILE
# ============================================================

txt_files = [
    f for f in os.listdir(FOLDER)
    if f.lower().endswith(".txt")
]

if not txt_files:
    raise Exception("No TXT file found.")

input_path = os.path.join(FOLDER, txt_files[0])
output_path = os.path.join(FOLDER, "new_combined.txt")

# ============================================================
# RULES
# ============================================================

SINGLE_ENDINGS = ("।", "/", "\\", "|", "1")

INVALID_DOUBLE_ENDINGS = (
    "।।",
    "॥",
    "//",
    "\\\\",
    "||",
    "11"
)

# ============================================================
# SPECIAL SECOND LINE PATTERN
# Handles:
# ॥ anything ॥
# ।। anything ।।
# || anything ||
# 11 anything 11
# WITH OPTIONAL SPACES
# ============================================================

SPECIAL_PATTERN = re.compile(
    r"""
    (
        ॥\s*.*?\s*॥ |
        ।।\s*.*?\s*।। |
        \|\|\s*.*?\s*\|\| |
        11\s*.*?\s*11
    )
    """,
    re.VERBOSE
)

# ============================================================
# READ FILE
# ============================================================

with open(input_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# ============================================================
# PROCESS
# ============================================================

formatted = []

for i in range(len(lines)):

    current_line = lines[i].rstrip("\n")
    stripped_current = current_line.strip()

    # --------------------------------------------------------
    # DETECT STANZA END
    # --------------------------------------------------------

    stanza_end = re.search(
        r'''
        (
            ॥+।*\s*.*?\s*॥+।* |
            ।।+\s*.*?\s*।।+ |
            \|\|\s*.*?\s*\|\| |
            11\s*.*?\s*11
        )
        ''',
        stripped_current,
        re.VERBOSE
    )

    # --------------------------------------------------------
    # INSERT SPACE BEFORE PAIR
    # --------------------------------------------------------

    if stanza_end:

        if len(formatted) >= 1:

            if formatted[-1].strip() != "":

                formatted.insert(len(formatted) - 1, "\n")

    # --------------------------------------------------------
    # ADD CURRENT LINE
    # --------------------------------------------------------

    formatted.append(current_line + "\n")

    # --------------------------------------------------------
    # INSERT SPACE AFTER STANZA
    # --------------------------------------------------------

    if stanza_end:

        formatted.append("\n")

# ============================================================
# WRITE OUTPUT
# ============================================================

with open(output_path, "w", encoding="utf-8") as f:
    f.writelines(formatted)

print("\nDone.")
print("Input :", input_path)
print("Output:", output_path)