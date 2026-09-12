#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build wake-word entries for keywords.txt.

It will:
1. convert Chinese text to tone-marked pinyin
2. split each syllable into its initial and final
3. check every token appears in tokens.txt
4. write the result in the keywords.txt format
"""

import sys
from pathlib import Path

try:
    from pypinyin import Style, lazy_pinyin
except ImportError:
    print("Missing dependency: pypinyin")
    print("Install it with: pip install pypinyin")
    sys.exit(1)


class KeywordGenerator:
    def __init__(self, model_dir: Path):
        """Set up the generator.

        Args:
            model_dir: the model directory, holding tokens.txt and keywords.txt
        """
        self.model_dir = Path(model_dir)
        self.tokens_file = self.model_dir / "tokens.txt"
        self.keywords_file = self.model_dir / "keywords.txt"

        # load the tokens we already have
        self.available_tokens = self._load_tokens()

        # the pinyin initials that get split off
        self.initials = [
            "b",
            "p",
            "m",
            "f",
            "d",
            "t",
            "n",
            "l",
            "g",
            "k",
            "h",
            "j",
            "q",
            "x",
            "zh",
            "ch",
            "sh",
            "r",
            "z",
            "c",
            "s",
            "y",
            "w",
        ]

    def _load_tokens(self) -> set:
        """
        Load every usable token from tokens.txt.
        """
        if not self.tokens_file.exists():
            print(f"Warning: no tokens file at {self.tokens_file}")
            return set()

        tokens = set()
        with open(self.tokens_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    # the format is either "token id" or just "token"
                    parts = line.split()
                    if parts:
                        tokens.add(parts[0])

        print(f"Loaded {len(tokens)} usable tokens")
        return tokens

    def _split_pinyin(self, pinyin: str) -> list:
        """Split a pinyin syllable into its initial and final.

        For example: "xiǎo" -> ["x", "iǎo"], "mǐ" -> ["m", "ǐ"], "ài" -> ["ài"] (no initial)
        """
        if not pinyin:
            return []

        # try the longest initials first, so zh, ch and sh match before z, c and s
        for initial in sorted(self.initials, key=len, reverse=True):
            if pinyin.startswith(initial):
                final = pinyin[len(initial) :]
                if final:
                    return [initial, final]
                else:
                    return [initial]

        # no initial at all
        return [pinyin]

    def chinese_to_keyword_format(self, chinese_text: str) -> str:
        """Turn Chinese text into the keyword format.

        Args:
            chinese_text: the Chinese text, e.g. "小米小米"

        Returns:
            the keyword line, e.g. "x iǎo m ǐ x iǎo m ǐ @小米小米"
        """
        # convert to tone-marked pinyin
        pinyin_list = lazy_pinyin(chinese_text, style=Style.TONE)

        # split each syllable
        split_parts = []
        missing_tokens = []

        for pinyin in pinyin_list:
            parts = self._split_pinyin(pinyin)

            # check each part is a known token
            for part in parts:
                if part not in self.available_tokens:
                    missing_tokens.append(part)
                split_parts.append(part)

        # assemble the line
        pinyin_str = " ".join(split_parts)
        keyword_line = f"{pinyin_str} @{chinese_text}"

        # warn about anything the model does not know
        if missing_tokens:
            print(
                f"Warning: these tokens are not in tokens.txt: {', '.join(set(missing_tokens))}"
            )
            print(f"   the keyword may not be recognised")

        return keyword_line

    def add_keyword(self, chinese_text: str, append: bool = True) -> bool:
        """Add a wake word to keywords.txt.

        Args:
            chinese_text: the wake word, in Chinese
            append: True appends, False overwrites

        Returns:
            whether it was added
        """
        try:
            # build the keyword line
            keyword_line = self.chinese_to_keyword_format(chinese_text)

            # skip it if it is already there
            if self.keywords_file.exists():
                with open(self.keywords_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    if f"@{chinese_text}" in content:
                        print(f"'{chinese_text}' is already in the file")
                        return False

            # write it out
            mode = "a" if append else "w"
            with open(self.keywords_file, mode, encoding="utf-8") as f:
                f.write(keyword_line + "\n")

            print(f"Added: {keyword_line}")
            return True

        except Exception as e:
            print(f"Could not add it: {e}")
            return False

    def batch_add_keywords(self, chinese_texts: list, overwrite: bool = False):
        """Add several wake words at once.

        Args:
            chinese_texts: the wake words
            overwrite: replace the existing file rather than appending
        """
        if overwrite:
            print("This will replace the existing keywords.txt")

        success_count = 0
        for text in chinese_texts:
            text = text.strip()
            if not text:
                continue

            if self.add_keyword(text, append=not overwrite):
                success_count += 1

            # everything after the first one appends
            overwrite = False

        print(f"\nDone: added {success_count} of {len(chinese_texts)} keywords")

    def list_keywords(self):
        """
        List the keywords currently in the file.
        """
        if not self.keywords_file.exists():
            print("There is no keywords.txt yet")
            return

        print(f"\nKeywords in {self.keywords_file}:")
        print("-" * 60)

        with open(self.keywords_file, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if line and not line.startswith("#"):
                    # show the readable part after the @
                    if "@" in line:
                        pinyin_part, chinese_part = line.split("@", 1)
                        print(
                            f"{i}. {chinese_part.strip():15s} -> {pinyin_part.strip()}"
                        )
                    else:
                        print(f"{i}. {line}")

        print("-" * 60)


def main():
    """
    Entry point.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Build wake-word entries for keywords.txt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # add one keyword
  python keyword_generator.py -a "小米小米"

  # add several at once
  python keyword_generator.py -b "小米小米" "你好小智" "贾维斯"

  # import from a file, one wake word per line
  python keyword_generator.py -f keywords_input.txt

  # list what is already there
  python keyword_generator.py -l

  # try a conversion without writing anything
  python keyword_generator.py -t "小米小米"
        """,
    )

    parser.add_argument(
        "-m",
        "--model-dir",
        default="models",
        help="the model directory (default: models)",
    )

    parser.add_argument("-a", "--add", help="add one keyword, given in Chinese")

    parser.add_argument(
        "-b", "--batch", nargs="+", help="add several keywords, separated by spaces"
    )

    parser.add_argument(
        "-f", "--file", help="import from a file, one wake word per line"
    )

    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="list the keywords already in the file",
    )

    parser.add_argument(
        "-t", "--test", help="try a conversion without writing anything"
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace the existing keywords instead of appending",
    )

    args = parser.parse_args()

    # work out the model directory
    if Path(args.model_dir).is_absolute():
        model_dir = Path(args.model_dir)
    else:
        # a relative path is taken from the project root
        script_dir = Path(__file__).parent
        project_root = script_dir.parent
        model_dir = project_root / args.model_dir

    if not model_dir.exists():
        print(f"No model directory at {model_dir}")
        sys.exit(1)

    print(f"Using model directory: {model_dir}")

    # build the generator
    generator = KeywordGenerator(model_dir)

    # do what was asked
    if args.test:
        # test mode
        print(f"\nConversion test:")
        keyword_line = generator.chinese_to_keyword_format(args.test)
        print(f"   in:  {args.test}")
        print(f"   out: {keyword_line}")

    elif args.add:
        # add one
        generator.add_keyword(args.add)

    elif args.batch:
        # add several
        generator.batch_add_keywords(args.batch, overwrite=args.overwrite)

    elif args.file:
        # import from a file
        input_file = Path(args.file)
        if not input_file.exists():
            print(f"No such file: {input_file}")
            sys.exit(1)

        with open(input_file, "r", encoding="utf-8") as f:
            keywords = [line.strip() for line in f if line.strip()]

        print(f"Importing {len(keywords)} keywords from the file")
        generator.batch_add_keywords(keywords, overwrite=args.overwrite)

    elif args.list:
        # just list them
        generator.list_keywords()

    else:
        # interactive mode
        print("\nWake-word generator (interactive)")
        print("Type a wake word in Chinese. Ctrl+C, or q, to quit.\n")

        try:
            while True:
                chinese = input("Wake word: ").strip()

                if not chinese or chinese.lower() == "q":
                    break

                generator.add_keyword(chinese)
                print()

        except KeyboardInterrupt:
            print("\n\nBye.")

    # finish by listing them all
    if not args.list and (args.add or args.batch or args.file):
        generator.list_keywords()


if __name__ == "__main__":
    main()
