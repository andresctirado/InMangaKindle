#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""
MangaDex Downloader - Download manga from mangadex.org with language selection
Based on InMangaKindle by Carleslc

Usage:
    python3 mangadex.py "blue-lock" --lang es --chapters 1..10 --format EPUB
    python3 mangadex.py "one-piece" --lang en --chapters 1..5
    python3 mangadex.py "my-hero-academia" --lang es-la --chapters "10, 15..20"
    
Language options:
    --lang es      Spanish (Castilian)
    --lang en      English
    --lang es-la   Latin American Spanish
    
Requirements:
    pip install requests colorama
"""

VERSION = '1.0'
NAME = 'MangaDexKindle'

import os
import re
import sys
import signal
import argparse
import tempfile
from multiprocessing import freeze_support

# Import shared dependencies
def install_dependencies(dependencies_file):
    from pathlib import Path
    import pkg_resources
    dependencies_path = Path(__file__).with_name(dependencies_file)
    dependencies = pkg_resources.parse_requirements(dependencies_path.open())
    try:
        for dependency in dependencies:
            pkg_resources.require(str(dependency))
    except pkg_resources.DistributionNotFound:
        import subprocess
        print("Some dependencies are missing, installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", dependencies_file])

install_dependencies("dependencies.txt")

import requests
from colorama import Fore, Style, init as init_console_colors

# MangaDex API URLs
API_BASE = "https://api.mangadex.org"
MANGA_DIR = './manga'

# Language codes mapping
LANGUAGE_CODES = {
    'es': 'es',       # Spanish (Castilian)
    'spanish': 'es',
    'en': 'en',       # English
    'english': 'en',
    'es-la': 'es-la', # Latin American Spanish
    'latin': 'es-la',
    'latam': 'es-la',
}

LANGUAGE_NAMES = {
    'es': 'Spanish (Castilian)',
    'en': 'English',
    'es-la': 'Latin American Spanish',
}

CHAPTERS_FORMAT = 'Format: start..end or chapters with commas. Example: --chapters "1..10" will download chapters 1-10.'

def set_args():
    global args
    parser = argparse.ArgumentParser(prog=NAME, description='Download manga from MangaDex with language selection')
    parser.add_argument("manga_name", help="manga name or MangaDex ID to download")
    parser.add_argument("--lang", "--language", help="Language: es (Spanish), en (English), es-la (Latin American Spanish)", 
                        default='es-la', choices=['es', 'spanish', 'en', 'english', 'es-la', 'latin', 'latam'])
    parser.add_argument("--chapters", "--chapter", help=f'chapters to download. {CHAPTERS_FORMAT}', nargs='+')
    parser.add_argument("--directory", help=f"directory to save downloads. Default: {MANGA_DIR}", default=MANGA_DIR)
    parser.add_argument("--single", action='store_true', help="merge all chapters in only one file")
    parser.add_argument("--rotate", action='store_true', help="rotate double pages")
    parser.add_argument("--profile", help='Device profile [Default = KPW (Kindle Paperwhite)]', default='KPW')
    parser.add_argument("--format", help='Output format (PNG, PDF, MOBI, EPUB, CBZ) [Default = EPUB]', default='EPUB')
    parser.add_argument("--fullsize", action='store_true', help="Do not stretch images to device resolution")
    parser.add_argument("--quality", help='Image quality: data (original) or data-saver (compressed) [Default = data]', 
                        default='data', choices=['data', 'data-saver'])
    parser.add_argument("--version", "-v", action='version', version=f'{NAME} {VERSION}')
    args = parser.parse_args()

def print_colored(message, *colors, end='\n'):
    for color in colors:
        print(color, end='', flush=True)
    print(message, end=end)
    print(Style.RESET_ALL, end='', flush=True)

def error(message, tip=''):
    print_colored(message, Fore.RED, Style.BRIGHT)
    if tip:
        print_colored(tip, Style.DIM)
    exit(1)

def print_dim(s, *colors):
    print_colored(s, Style.DIM, *colors)

def cancellable():
    def cancel(s, f):
        print_dim('\nCancelled')
        exit()
    try:
        signal.signal(signal.SIGINT, cancel)
    except:
        pass

def network_error():
    error('Network error', 'Are you connected to Internet?')

def strip_path(path, keep):
    return ''.join(c for c in path if c.isalnum() or c in keep).strip()

def plural(size):
    return 's' if size != 1 else ''

def write_file(path, data):
    dirname = os.path.dirname(path)
    if not os.path.exists(dirname):
        os.makedirs(dirname)
    with open(path, 'wb') as handler:
        handler.write(data)

def encode(title):
    return re.sub(r'\W+', '-', title)

def manga_directory(manga):
    return f'{MANGA_DIR}/{manga}'

def chapter_directory(manga, chapter):
    chapter_str = f'{chapter:g}' if isinstance(chapter, float) else str(chapter)
    return f'{manga_directory(manga)}/{chapter_str}'

# MangaDex API Functions

def api_request(endpoint, params=None):
    """Make a request to the MangaDex API"""
    url = f"{API_BASE}{endpoint}"
    try:
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 429:
            error('Rate limited by MangaDex API', 'Please wait a few minutes and try again.')
        else:
            return None
    except requests.RequestException as e:
        network_error()

def search_manga(query):
    """Search for manga by title"""
    print_dim(f'Searching for "{query}" on MangaDex...')
    
    params = {
        'title': query,
        'limit': 10,
        'includes[]': ['cover_art'],
        'order[relevance]': 'desc'
    }
    
    result = api_request('/manga', params)
    
    if result and result.get('data'):
        return result['data']
    return []

def get_manga_by_id(manga_id):
    """Get manga details by ID"""
    result = api_request(f'/manga/{manga_id}', {'includes[]': ['cover_art']})
    
    if result and result.get('data'):
        return result['data']
    return None

def get_manga_title(manga_data):
    """Extract manga title from API response"""
    titles = manga_data.get('attributes', {}).get('title', {})
    # Prefer English, then Japanese romanized, then any available
    if 'en' in titles:
        return titles['en']
    if 'ja-ro' in titles:
        return titles['ja-ro']
    if 'ja' in titles:
        return titles['ja']
    # Return first available
    return next(iter(titles.values()), 'Unknown')

def get_manga_chapters(manga_id, language_code, limit=500):
    """Get all chapters for a manga in a specific language"""
    print_dim(f'Fetching chapters in {LANGUAGE_NAMES.get(language_code, language_code)}...')
    
    chapters = []
    offset = 0
    
    while True:
        params = {
            'manga': manga_id,
            'translatedLanguage[]': language_code,
            'order[chapter]': 'asc',
            'limit': min(limit, 500),
            'offset': offset,
            'includes[]': ['scanlation_group']
        }
        
        result = api_request('/chapter', params)
        
        if not result or not result.get('data'):
            break
        
        batch = result['data']
        chapters.extend(batch)
        
        total = result.get('total', 0)
        offset += len(batch)
        
        if offset >= total or len(batch) == 0:
            break
    
    return chapters

def get_chapter_images(chapter_id, quality='data'):
    """Get image URLs for a specific chapter"""
    result = api_request(f'/at-home/server/{chapter_id}')
    
    if not result:
        return []
    
    base_url = result.get('baseUrl', '')
    chapter_data = result.get('chapter', {})
    chapter_hash = chapter_data.get('hash', '')
    
    # Choose quality: 'data' for original or 'dataSaver' for compressed
    quality_key = 'dataSaver' if quality == 'data-saver' else 'data'
    filenames = chapter_data.get(quality_key, [])
    
    # Construct full URLs
    quality_path = 'data-saver' if quality == 'data-saver' else 'data'
    image_urls = [f'{base_url}/{quality_path}/{chapter_hash}/{filename}' for filename in filenames]
    
    return image_urls

def download_image(url, path, page_num, total_pages):
    """Download a single image"""
    if os.path.isfile(path):
        print_colored(f'Page {page_num}/{total_pages} - Already exists', Fore.YELLOW)
        return True
    
    try:
        response = requests.get(url, timeout=60)
        if response.status_code == 200:
            write_file(path, response.content)
            print_colored(f'Page {page_num}/{total_pages} ({100*page_num//total_pages}%)', Fore.GREEN)
            return True
        else:
            print_colored(f'Page {page_num}/{total_pages} - Failed ({response.status_code})', Fore.RED)
            return False
    except Exception as e:
        print_colored(f'Page {page_num}/{total_pages} - Error: {e}', Fore.RED)
        return False

def parse_chapter_intervals(chapter_intervals_str, all_chapters):
    """Parse chapter range string into list of chapters"""
    # Create a mapping of chapter numbers to chapter data
    chapter_numbers = []
    for ch in all_chapters:
        ch_num = ch.get('attributes', {}).get('chapter')
        if ch_num:
            try:
                chapter_numbers.append(float(ch_num))
            except ValueError:
                continue
    
    if not chapter_numbers:
        return []
    
    last = max(chapter_numbers)
    
    def parse_chapter(chapter):
        return last if chapter.strip() == 'last' else float(chapter.strip())
    
    chapters_to_download = set()
    
    for part in chapter_intervals_str.split(','):
        part = part.strip()
        if '..' in part:
            start, end = part.split('..')
            start_num = parse_chapter(start)
            end_num = parse_chapter(end)
            for ch_num in chapter_numbers:
                if start_num <= ch_num <= end_num:
                    chapters_to_download.add(ch_num)
        else:
            chapters_to_download.add(parse_chapter(part))
    
    return sorted(chapters_to_download)

def copy_all(name_path_list, to_path):
    import errno, shutil
    def copy(src, dest):
        try:
            shutil.copytree(src, dest)
        except OSError as e:
            if e.errno == errno.ENOTDIR:
                shutil.copy(src, dest)
            else:
                error(str(e))
    for name, path in name_path_list:
        copy(path, f'{to_path}/{name}')

def files(dir, extension=''):
    if not os.path.isdir(dir):
        return []
    def filename(file):
        return file.rsplit('.', 1)[0]
    result = []
    for file in os.listdir(dir):
        path = os.path.abspath(f'{dir}/{file}')
        if os.path.isfile(path) and file.endswith(extension):
            result.append((filename(file), path))
    return result

def split_rotate_2_pages(rotate):
    return str(1 if rotate else 0)

def single_flag(single):
    return str(0 if single else 2)

def chapters_to_intervals_string(sorted_chapters, start_end_sep='-', interval_sep=','):
    if not sorted_chapters:
        return ''
    
    intervals = []
    start = sorted_chapters[0]
    end = start
    
    for ch in sorted_chapters[1:]:
        if ch <= end + 1:
            end = ch
        else:
            if start == end:
                intervals.append(f'{start:g}')
            else:
                intervals.append(f'{start:g}{start_end_sep}{end:g}')
            start = end = ch
    
    if start == end:
        intervals.append(f'{start:g}')
    else:
        intervals.append(f'{start:g}{start_end_sep}{end:g}')
    
    return interval_sep.join(intervals)


if __name__ == "__main__":
    cancellable()
    freeze_support()
    init_console_colors()
    
    set_args()
    
    MANGA_DIR = strip_path(args.directory, set(['_', '-', ' ', '.', '/']))
    manga_query = args.manga_name.strip()
    language_code = LANGUAGE_CODES.get(args.lang.lower(), 'es')
    
    print_colored(f"Language: {LANGUAGE_NAMES.get(language_code, language_code)}", Style.BRIGHT, Fore.CYAN)
    
    # Check if it's a MangaDex UUID (36 characters with dashes)
    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)
    
    if uuid_pattern.match(manga_query):
        # Direct manga ID provided
        print_dim(f'Using MangaDex ID: {manga_query}')
        manga_data = get_manga_by_id(manga_query)
        if not manga_data:
            error(f"Manga not found with ID: {manga_query}")
        manga_id = manga_query
        manga_title = get_manga_title(manga_data)
    else:
        # Search for manga by name
        print_colored(f"Searching '{manga_query}' on MangaDex...", Style.BRIGHT)
        results = search_manga(manga_query)
        
        if not results:
            error(f"No manga found for '{manga_query}'", 
                  "Try using the exact MangaDex manga ID instead.")
        
        # Show results and select the first one
        manga_data = results[0]
        manga_id = manga_data['id']
        manga_title = get_manga_title(manga_data)
        
        if len(results) > 1:
            print_dim(f'Found {len(results)} results, using best match:')
        print_colored(f"  → {manga_title}", Fore.CYAN)
        print_dim(f"  ID: {manga_id}")
        
        # Show other results as alternatives
        if len(results) > 1:
            print_dim('\nOther results:')
            for i, r in enumerate(results[1:5], 2):
                alt_title = get_manga_title(r)
                print_dim(f'  {i}. {alt_title} ({r["id"]})')
    
    print_colored(manga_title, Fore.BLUE, Style.BRIGHT)
    
    # Get chapters for the specified language
    all_chapters = get_manga_chapters(manga_id, language_code)
    
    if not all_chapters:
        available_langs = []
        for lang in ['es', 'en', 'es-la']:
            test_chapters = get_manga_chapters(manga_id, lang, limit=1)
            if test_chapters:
                available_langs.append(f"{lang} ({LANGUAGE_NAMES[lang]})")
        
        tip = ''
        if available_langs:
            tip = f"Available languages: {', '.join(available_langs)}"
        error(f"No chapters found in {LANGUAGE_NAMES.get(language_code, language_code)}", tip)
    
    # Build chapter number mapping
    chapter_map = {}  # chapter_number -> chapter_data
    for ch in all_chapters:
        ch_num = ch.get('attributes', {}).get('chapter')
        if ch_num:
            try:
                ch_num_float = float(ch_num)
                # Keep the first (or most recent) version of each chapter
                if ch_num_float not in chapter_map:
                    chapter_map[ch_num_float] = ch
            except ValueError:
                continue
    
    available_chapters = sorted(chapter_map.keys())
    print_dim(f'{len(available_chapters)} chapter{plural(len(available_chapters))} available')
    
    if not available_chapters:
        error("No valid chapters found")
    
    # Parse chapters to download
    if args.chapters:
        chapters_str = ' '.join(args.chapters)
        CHAPTERS = parse_chapter_intervals(chapters_str, all_chapters)
        # Filter only available chapters
        CHAPTERS = [ch for ch in CHAPTERS if ch in available_chapters]
    else:
        CHAPTERS = available_chapters
    
    if not CHAPTERS:
        error("No chapters found to download")
    
    print_dim(f'{len(CHAPTERS)} chapter{plural(len(CHAPTERS))} will be downloaded - Cancel with Ctrl+C')
    
    # Download chapters
    manga_encoded = encode(manga_title)
    
    for chapter in CHAPTERS:
        chapter_str = f'{chapter:g}'
        chapter_data = chapter_map.get(chapter)
        
        if not chapter_data:
            print_colored(f'Chapter {chapter_str} not found', Fore.RED)
            continue
        
        chapter_id = chapter_data['id']
        print_colored(f'Downloading {manga_title} Chapter {chapter_str}', Fore.YELLOW, Style.BRIGHT)
        
        image_urls = get_chapter_images(chapter_id, args.quality)
        
        if not image_urls:
            print_colored(f'No images found for chapter {chapter_str}', Fore.RED)
            continue
        
        chapter_dir = chapter_directory(manga_encoded, chapter)
        
        for i, img_url in enumerate(image_urls, 1):
            # Determine extension from URL
            if '.jpg' in img_url.lower() or '.jpeg' in img_url.lower():
                ext = 'jpg'
            elif '.png' in img_url.lower():
                ext = 'png'
            elif '.gif' in img_url.lower():
                ext = 'gif'
            else:
                ext = 'webp'
            img_path = f'{chapter_dir}/{i}.{ext}'
            download_image(img_url, img_path, i, len(image_urls))
    
    # Convert to e-reader format
    extension = f'.{args.format.lower()}'
    args.format = args.format.upper()
    
    if args.format != 'PNG':
        print_colored(f'Converting to {args.format}...', Fore.BLUE, Style.BRIGHT)
        
        if args.format == 'PDF':
            import img2pdf
            for chapter in CHAPTERS:
                chapter_dir = chapter_directory(manga_encoded, chapter)
                page_paths = []
                for ext in ['jpg', 'png', 'webp', 'gif']:
                    for name, path in sorted(files(chapter_dir, ext), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
                        page_paths.append(path)
                
                if page_paths:
                    path = f'{MANGA_DIR}/{manga_title} {chapter:g}{extension}'
                    with open(path, "wb") as f:
                        f.write(img2pdf.convert(page_paths))
                    print_colored(f'DONE: {os.path.abspath(path)}', Fore.GREEN, Style.BRIGHT)
        else:
            # Use KCC for EPUB/MOBI/CBZ
            from kindlecomicconverter.comic2ebook import main as manga2ebook
            
            argv = ['--output', MANGA_DIR, '-p', args.profile, '--manga-style', '--hq', '-f', args.format, 
                    '--batchsplit', single_flag(args.single), '-u', '-r', split_rotate_2_pages(args.rotate)]
            
            if not args.fullsize:
                argv.append('-s')
            
            if args.single:
                chapter_interval = chapters_to_intervals_string(CHAPTERS)
                with tempfile.TemporaryDirectory() as temp:
                    copy_all([(str(int(ch) if ch == int(ch) else ch), chapter_directory(manga_encoded, ch)) for ch in CHAPTERS], temp)
                    title = f'{manga_title} {chapter_interval}'
                    print_colored(title, Fore.BLUE)
                    argv_full = argv + ['--title', title, temp]
                    manga2ebook(argv_full)
                    path = f'{MANGA_DIR}/{manga_title} {chapter_interval}{extension}'
                    temp_output = f'{MANGA_DIR}/{os.path.basename(temp)}{extension}'
                    if os.path.exists(temp_output):
                        os.rename(temp_output, path)
                        print_colored(f'DONE: {os.path.abspath(path)}', Fore.GREEN, Style.BRIGHT)
            else:
                for chapter in CHAPTERS:
                    title = f'{manga_title} {chapter:g}'
                    print_colored(title, Fore.BLUE)
                    chapter_dir = chapter_directory(manga_encoded, chapter)
                    argv_chapter = argv + ['--title', title, chapter_dir]
                    try:
                        manga2ebook(argv_chapter)
                        path = f'{MANGA_DIR}/{manga_title} {chapter:g}{extension}'
                        temp_output = f'{MANGA_DIR}/{chapter:g}{extension}'
                        if os.path.exists(temp_output):
                            os.rename(temp_output, path)
                        print_colored(f'DONE: {os.path.abspath(path)}', Fore.GREEN, Style.BRIGHT)
                    except Exception as e:
                        print_colored(f'Conversion error for chapter {chapter:g}: {e}', Fore.RED)
    else:
        chapter_interval = chapters_to_intervals_string(CHAPTERS, interval_sep=', ')
        directory = os.path.abspath(manga_directory(manga_encoded))
        print_colored(f'DONE: {directory} ({chapter_interval})', Fore.GREEN, Style.BRIGHT)
