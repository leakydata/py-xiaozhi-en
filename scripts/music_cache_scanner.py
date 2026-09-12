#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Music cache scanner: walks cache/music, reads the tags, and builds a local playlist.

Needs mutagen: pip install mutagen
"""

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

try:
    from mutagen import File as MutagenFile
    from mutagen.id3 import ID3NoHeaderError
except ImportError:
    print("The mutagen library is required")
    print("Install it with: pip install mutagen")
    sys.exit(1)

# the project root
PROJECT_ROOT = Path(__file__).parent.parent


class MusicMetadata:
    """
    The tags read from one music file.
    """

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.filename = file_path.name
        self.file_id = (
            file_path.stem
        )  # the file name without its extension, which is the track id
        self.file_size = file_path.stat().st_size
        self.creation_time = datetime.fromtimestamp(file_path.stat().st_ctime)
        self.modification_time = datetime.fromtimestamp(file_path.stat().st_mtime)

        # what was read from the file
        self.title = None
        self.artist = None
        self.album = None
        self.genre = None
        self.year = None
        self.duration = None  # in seconds
        self.bitrate = None
        self.sample_rate = None

        # a hash of the file, used to spot duplicates
        self.file_hash = self._calculate_hash()

    def _calculate_hash(self) -> str:
        """
        MD5 of the first 1MB only, so a large file does not take forever.
        """
        try:
            hash_md5 = hashlib.md5()
            with open(self.file_path, "rb") as f:
                # hash just the first 1MB
                chunk = f.read(1024 * 1024)
                hash_md5.update(chunk)
            return hash_md5.hexdigest()[:16]  # the first 16 hex digits are plenty
        except Exception:
            return "unknown"

    def extract_metadata(self) -> bool:
        """
        Read the tags out of the file.
        """
        try:
            audio_file = MutagenFile(self.file_path)
            if audio_file is None:
                return False

            # the basics
            if hasattr(audio_file, "info"):
                self.duration = getattr(audio_file.info, "length", None)
                self.bitrate = getattr(audio_file.info, "bitrate", None)
                self.sample_rate = getattr(audio_file.info, "sample_rate", None)

            # the ID3 tags
            tags = audio_file.tags if audio_file.tags else {}

            # title
            self.title = self._get_tag_value(tags, ["TIT2", "TITLE", "\xa9nam"])

            # artist
            self.artist = self._get_tag_value(tags, ["TPE1", "ARTIST", "\xa9ART"])

            # album
            self.album = self._get_tag_value(tags, ["TALB", "ALBUM", "\xa9alb"])

            # genre
            self.genre = self._get_tag_value(tags, ["TCON", "GENRE", "\xa9gen"])

            # year
            year_raw = self._get_tag_value(tags, ["TDRC", "DATE", "YEAR", "\xa9day"])
            if year_raw:
                # pull the year out
                year_str = str(year_raw)
                if year_str.isdigit():
                    self.year = int(year_str)
                else:
                    # try to find a year inside a date string
                    import re

                    year_match = re.search(r"(\d{4})", year_str)
                    if year_match:
                        self.year = int(year_match.group(1))

            return True

        except ID3NoHeaderError:
            # no ID3 tags at all, which is not an error
            return True
        except Exception as e:
            print(f"could not read the tags from {self.filename}: {e}")
            return False

    def _get_tag_value(self, tags: dict, tag_names: List[str]) -> Optional[str]:
        """
        Take the value from whichever of these tag names is present.
        """
        for tag_name in tag_names:
            if tag_name in tags:
                value = tags[tag_name]
                if isinstance(value, list) and value:
                    return str(value[0])
                elif value:
                    return str(value)
        return None

    def format_duration(self) -> str:
        """
        Format the duration.
        """
        if self.duration is None:
            return "unknown"

        minutes = int(self.duration) // 60
        seconds = int(self.duration) % 60
        return f"{minutes:02d}:{seconds:02d}"

    def format_file_size(self) -> str:
        """
        Format the file size.
        """
        size = self.file_size
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"

    def to_dict(self) -> Dict:
        """
        As a dict.
        """
        return {
            "file_id": self.file_id,
            "filename": self.filename,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "genre": self.genre,
            "year": self.year,
            "duration": self.duration,
            "duration_formatted": self.format_duration(),
            "bitrate": self.bitrate,
            "sample_rate": self.sample_rate,
            "file_size": self.file_size,
            "file_size_formatted": self.format_file_size(),
            "file_hash": self.file_hash,
            "creation_time": self.creation_time.isoformat(),
            "modification_time": self.modification_time.isoformat(),
        }


class MusicCacheScanner:
    """
    The music cache scanner.
    """

    def __init__(self, cache_dir: Path = None):
        self.cache_dir = cache_dir or PROJECT_ROOT / "cache" / "music"
        self.playlist: List[MusicMetadata] = []
        self.scan_stats = {
            "total_files": 0,
            "success_count": 0,
            "error_count": 0,
            "total_duration": 0,
            "total_size": 0,
        }

    def scan_cache(self) -> bool:
        """
        Walk the cache directory.
        """
        print(f"🎵 Scanning the music cache: {self.cache_dir}")

        if not self.cache_dir.exists():
            print(f"❌ No cache directory at {self.cache_dir}")
            return False

        # find the music files
        music_files = []
        for pattern in ["*.mp3", "*.m4a", "*.flac", "*.wav", "*.ogg"]:
            music_files.extend(self.cache_dir.glob(pattern))

        if not music_files:
            print("📁 No music files in the cache")
            return False

        self.scan_stats["total_files"] = len(music_files)
        print(f"📊 Found {len(music_files)} music files")

        # read each one
        for i, file_path in enumerate(music_files, 1):
            print(f"🔍 [{i}/{len(music_files)}] reading: {file_path.name}")

            try:
                metadata = MusicMetadata(file_path)

                if metadata.extract_metadata():
                    self.playlist.append(metadata)
                    self.scan_stats["success_count"] += 1

                    # running totals
                    if metadata.duration:
                        self.scan_stats["total_duration"] += metadata.duration
                    self.scan_stats["total_size"] += metadata.file_size

                    # show what we found
                    display_title = metadata.title or "Unknown Title"
                    display_artist = metadata.artist or "Unknown Artist"
                    print(
                        f"   ✅ {display_title} - {display_artist} ({metadata.format_duration()})"
                    )
                else:
                    self.scan_stats["error_count"] += 1
                    print("   ❌ could not read the tags")

            except Exception as e:
                self.scan_stats["error_count"] += 1
                print(f"   ❌ failed: {e}")

        return True

    def remove_duplicates(self):
        """
        Drop duplicate files, matched on their hash.
        """
        seen_hashes = set()
        unique_playlist = []
        duplicates = []

        for metadata in self.playlist:
            if metadata.file_hash in seen_hashes:
                duplicates.append(metadata)
            else:
                seen_hashes.add(metadata.file_hash)
                unique_playlist.append(metadata)

        if duplicates:
            print(f"🔄 Found {len(duplicates)} duplicates:")
            for dup in duplicates:
                print(f"   - {dup.filename}")

        self.playlist = unique_playlist

    def sort_playlist(self, sort_by: str = "artist"):
        """
        Sort the playlist.
        """
        sort_functions = {
            "artist": lambda x: (
                x.artist or "Unknown",
                x.album or "Unknown",
                x.title or "Unknown",
            ),
            "title": lambda x: x.title or "Unknown",
            "album": lambda x: (x.album or "Unknown", x.artist or "Unknown"),
            "duration": lambda x: x.duration or 0,
            "file_size": lambda x: x.file_size,
            "creation_time": lambda x: x.creation_time,
        }

        if sort_by in sort_functions:
            self.playlist.sort(key=sort_functions[sort_by])
            print(f"📋 Playlist sorted by {sort_by}")

    def print_statistics(self):
        """
        Print the scan statistics.
        """
        stats = self.scan_stats
        print("\n📊 Scan summary:")
        print(f"   files:     {stats['total_files']}")
        print(f"   read OK:   {stats['success_count']}")
        print(f"   failed:    {stats['error_count']}")
        print(
            f"   success:   {stats['success_count'] / stats['total_files'] * 100:.1f}%"
        )

        # total playing time
        total_hours = stats["total_duration"] // 3600
        total_minutes = (stats["total_duration"] % 3600) // 60
        print(f"   total time: {total_hours}h {total_minutes}m")

        # total size
        total_size_mb = stats["total_size"] / (1024 * 1024)
        print(f"   total size: {total_size_mb:.1f} MB")

        # averages
        if stats["success_count"] > 0:
            avg_duration = stats["total_duration"] / stats["success_count"]
            avg_size = stats["total_size"] / stats["success_count"]
            print(
                f"   mean time: {int(avg_duration // 60)}:{int(avg_duration % 60):02d}"
            )
            print(f"   mean size: {avg_size / (1024 * 1024):.1f} MB")

    def print_playlist(self, limit: int = None):
        """
        Print the playlist.
        """
        print(f"\n🎵 Local playlist ({len(self.playlist)} tracks)")
        print("=" * 80)

        for i, metadata in enumerate(
            self.playlist[:limit] if limit else self.playlist, 1
        ):
            title = metadata.title or "Unknown Title"
            artist = metadata.artist or "Unknown Artist"
            album = metadata.album or "Unknown Album"
            duration = metadata.format_duration()

            print(f"{i:3d}. {title}")
            print(f"     artist: {artist}")
            print(f"     album:  {album}")
            print(f"     length: {duration} | id: {metadata.file_id}")
            print()

        if limit and len(self.playlist) > limit:
            print(f"... and {len(self.playlist) - limit} more")

    def export_playlist(self, output_file: Path = None, format: str = "json"):
        """
        Export the playlist.
        """
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = PROJECT_ROOT / f"local_playlist_{timestamp}.{format}"

        try:
            if format == "json":
                playlist_data = {
                    "metadata": {
                        "generated_at": datetime.now().isoformat(),
                        "cache_directory": str(self.cache_dir),
                        "total_songs": len(self.playlist),
                        "statistics": self.scan_stats,
                    },
                    "playlist": [metadata.to_dict() for metadata in self.playlist],
                }

                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(playlist_data, f, ensure_ascii=False, indent=2)

            elif format == "m3u":
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write("#EXTM3U\n")
                    for metadata in self.playlist:
                        title = metadata.title or metadata.filename
                        artist = metadata.artist or "Unknown Artist"
                        duration = int(metadata.duration) if metadata.duration else -1

                        f.write(f"#EXTINF:{duration},{artist} - {title}\n")
                        f.write(f"{metadata.file_path}\n")

            print(f"📄 Playlist written to {output_file}")
            return output_file

        except Exception as e:
            print(f"❌ Export failed: {e}")
            return None

    def search_songs(self, query: str) -> List[MusicMetadata]:
        """
        Search the playlist.
        """
        query = query.lower()
        results = []

        for metadata in self.playlist:
            # match against the title, artist and album
            searchable_text = " ".join(
                filter(
                    None,
                    [
                        metadata.title,
                        metadata.artist,
                        metadata.album,
                        metadata.filename,
                    ],
                )
            ).lower()

            if query in searchable_text:
                results.append(metadata)

        return results

    def get_artists(self) -> Dict[str, List[MusicMetadata]]:
        """
        Group by artist.
        """
        artists = {}
        for metadata in self.playlist:
            artist = metadata.artist or "Unknown Artist"
            if artist not in artists:
                artists[artist] = []
            artists[artist].append(metadata)
        return artists

    def get_albums(self) -> Dict[str, List[MusicMetadata]]:
        """
        Group by album.
        """
        albums = {}
        for metadata in self.playlist:
            album_key = f"{metadata.album or 'Unknown Album'} - {metadata.artist or 'Unknown Artist'}"
            if album_key not in albums:
                albums[album_key] = []
            albums[album_key].append(metadata)
        return albums


def main():
    """
    Entry point.
    """
    print("🎵 Music cache scanner")
    print("=" * 50)

    # build the scanner
    scanner = MusicCacheScanner()

    # scan
    if not scanner.scan_cache():
        return

    # drop duplicates
    scanner.remove_duplicates()

    # sort
    scanner.sort_playlist("artist")

    # show the summary
    scanner.print_statistics()

    # show the playlist, first 20 only
    scanner.print_playlist(limit=20)

    # the menu
    while True:
        print("\n" + "=" * 50)
        print("What would you like to do?")
        print("1. show the whole playlist")
        print("2. group by artist")
        print("3. group by album")
        print("4. search")
        print("5. export as JSON")
        print("6. export as M3U")
        print("7. re-sort")
        print("0. quit")

        choice = input("\nChoose 0-7: ").strip()

        if choice == "0":
            break
        elif choice == "1":
            scanner.print_playlist()
        elif choice == "2":
            artists = scanner.get_artists()
            for artist, songs in artists.items():
                print(f"\n🎤 {artist} ({len(songs)} tracks)")
                for song in songs:
                    title = song.title or song.filename
                    print(f"   - {title} ({song.format_duration()})")
        elif choice == "3":
            albums = scanner.get_albums()
            for album, songs in albums.items():
                print(f"\n💿 {album} ({len(songs)} tracks)")
                for song in songs:
                    title = song.title or song.filename
                    print(f"   - {title} ({song.format_duration()})")
        elif choice == "4":
            query = input("Search for: ").strip()
            if query:
                results = scanner.search_songs(query)
                if results:
                    print(f"\n🔍 {len(results)} matches:")
                    for i, song in enumerate(results, 1):
                        title = song.title or song.filename
                        artist = song.artist or "Unknown Artist"
                        print(f"   {i}. {title} - {artist} ({song.format_duration()})")
                else:
                    print("🔍 Nothing matched")
        elif choice == "5":
            scanner.export_playlist(format="json")
        elif choice == "6":
            scanner.export_playlist(format="m3u")
        elif choice == "7":
            print("Sort by:")
            print("1. artist")
            print("2. title")
            print("3. album")
            print("4. length")
            print("5. file size")
            print("6. date added")

            sort_choice = input("Choose 1-6: ").strip()
            sort_map = {
                "1": "artist",
                "2": "title",
                "3": "album",
                "4": "duration",
                "5": "file_size",
                "6": "creation_time",
            }

            if sort_choice in sort_map:
                scanner.sort_playlist(sort_map[sort_choice])
                print("✅ Sorted")
        else:
            print("❌ Not one of the options")

    print("\n👋 Bye.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted, quitting.")
    except Exception as e:
        print(f"\n❌ Something went wrong: {e}")
        import traceback

        traceback.print_exc()
