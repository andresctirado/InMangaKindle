#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""
SenshiManga Downloader - Download manga from senshimanga.capibaratraductor.com
Based on InMangaKindle by Carleslc

Usage:
    python3 senshi.py "blue-lock" --chapters 1..10 --format EPUB
    
Requirements:
    pip install playwright
    playwright install chromium
"""

VERSION = '1.0'
NAME = 'SenshiMangaKindle'

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
from bs4 import BeautifulSoup
from colorama import Fore, Style, init as init_console_colors

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright not installed. Installing...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    subprocess.check_call(["playwright", "install", "chromium"])
    from playwright.sync_api import sync_playwright

# SenshiManga URLs
PROVIDER_WEBSITE = "https://senshimanga.capibaratraductor.com"
MANGA_URL = f"{PROVIDER_WEBSITE}/manga"

MANGA_DIR = './manga'
BROWSER = None
BROWSER_PAGE = None

CHAPTERS_FORMAT = 'Format: start..end or chapters with commas. Example: --chapters "1..10" will download chapters 1-10.'

def set_args():
    global args
    parser = argparse.ArgumentParser(prog=NAME, description='Download manga from SenshiManga')
    parser.add_argument("manga_slug", help="manga slug to download (e.g., 'blue-lock')")
    parser.add_argument("--chapters", "--chapter", help=f'chapters to download. {CHAPTERS_FORMAT}', nargs='+')
    parser.add_argument("--directory", help=f"directory to save downloads. Default: {MANGA_DIR}", default=MANGA_DIR)
    parser.add_argument("--single", action='store_true', help="merge all chapters in only one file")
    parser.add_argument("--rotate", action='store_true', help="rotate double pages")
    parser.add_argument("--profile", help='Device profile [Default = KPW (Kindle Paperwhite)]', default='KPW')
    parser.add_argument("--format", help='Output format (PNG, PDF, MOBI, EPUB, CBZ) [Default = EPUB]', default='EPUB')
    parser.add_argument("--fullsize", action='store_true', help="Do not stretch images to device resolution")
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
    cleanup_browser()
    exit(1)

def print_dim(s, *colors):
    print_colored(s, Style.DIM, *colors)

def cancellable():
    def cancel(s, f):
        print_dim('\nCancelled')
        cleanup_browser()
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

# Browser management
_playwright = None
_browser = None

def get_browser():
    global _playwright, _browser
    if _browser is None:
        print_dim('Starting browser...')
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(headless=True)
    return _browser

def cleanup_browser():
    global _playwright, _browser
    if _browser:
        _browser.close()
        _browser = None
    if _playwright:
        _playwright.stop()
        _playwright = None

def download_image(url, path, page_num, total_pages):
    """Download a single image"""
    if os.path.isfile(path):
        print_colored(f'Page {page_num}/{total_pages} - Already exists', Fore.YELLOW)
        return True
    
    try:
        response = requests.get(url, timeout=30)
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

def get_manga_info(slug):
    """Get manga info and chapter list using browser"""
    url = f"{MANGA_URL}/{slug}"
    print_dim(f'Fetching manga info from {url}...')
    
    try:
        browser = get_browser()
        page = browser.new_page()
        page.goto(url, wait_until='domcontentloaded') # domcontentloaded is enough for astro-islands
        page.wait_for_timeout(3000)
        
        # Extract manga title
        title_elem = page.query_selector('h1')
        manga_title = title_elem.inner_text().strip() if title_elem else slug.replace('-', ' ').title()
        
        chapters = set()
        
        # Method 1: Try extracting from Astro Island props (Most reliable)
        island = page.query_selector('astro-island[component-export="MangaView"]')
        if island:
            props = island.get_attribute('props')
            if props:
                # Regex to find chapter numbers in the props JSON structure
                # Pattern appears to be "number":[0,123] or similar
                matches = re.findall(r'"number":\[\d+,(\d+(?:\.\d+)?)\]', props)
                for m in matches:
                    chapters.add(float(m))
                    
        # Method 2: Fallback to link extraction if Method 1 fails
        if not chapters:
            chapter_links = page.query_selector_all(f'a[href*="/manga/{slug}/chapters/"]')
            for link in chapter_links:
                href = link.get_attribute('href')
                if href:
                    match = re.search(r'/chapters/(\d+(?:\.\d+)?)', href)
                    if match:
                        chapters.add(float(match.group(1)))
        
        page.close()
        
        return {
            'title': manga_title,
            'slug': slug,
            'chapters': sorted(chapters)
        }
    except Exception as e:
        error(f"Failed to get manga info: {e}")

def get_chapter_images(slug, chapter_num):
    """Get all image URLs for a specific chapter using browser"""
    # Format chapter number (1.0 -> 1, 1.5 -> 1.5)
    chapter_str = str(int(chapter_num)) if chapter_num == int(chapter_num) else str(chapter_num)
    url = f"{MANGA_URL}/{slug}/chapters/{chapter_str}?page=1"
    print_dim(f'Fetching chapter {chapter_str} images...')
    
    try:
        browser = get_browser()
        page = browser.new_page()
        page.goto(url, wait_until='networkidle')
        page.wait_for_timeout(3000)  # Wait for images to load
        
        # Find all manga page images
        images = page.query_selector_all('img[alt^="Página "]')
        
        image_data = []
        for img in images:
            alt = img.get_attribute('alt')
            src = img.get_attribute('src')
            if src and alt:
                try:
                    page_num = int(alt.replace('Página ', ''))
                    image_data.append((page_num, src))
                except ValueError:
                    continue
        
        page.close()
        
        # Sort by page number
        image_data.sort(key=lambda x: x[0])
        return [url for _, url in image_data]
    
    except Exception as e:
        error(f"Failed to get chapter images: {e}")

def parse_chapter_intervals(chapter_intervals_str, all_chapters):
    """Parse chapter range string into list of chapters"""
    last = max(all_chapters) if all_chapters else 1
    
    def parse_chapter(chapter):
        return last if chapter == 'last' else float(chapter)
    
    chapters_to_download = []
    
    for part in chapter_intervals_str.split(','):
        part = part.strip()
        if '..' in part:
            start, end = part.split('..')
            start_num = parse_chapter(start.strip())
            end_num = parse_chapter(end.strip())
            for ch in all_chapters:
                if start_num <= ch <= end_num:
                    chapters_to_download.append(ch)
        else:
            chapters_to_download.append(parse_chapter(part))
    
    return sorted(set(chapters_to_download))

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
    manga_slug = args.manga_slug.strip().lower()
    
    # Remove URL if provided, extract just slug
    if 'senshimanga' in manga_slug:
        match = re.search(r'/manga/([^/]+)', manga_slug)
        if match:
            manga_slug = match.group(1)
    
    print_colored(f"Searching '{manga_slug}' on SenshiManga...", Style.BRIGHT)
    
    # Get manga info
    manga_info = get_manga_info(manga_slug)
    manga_title = manga_info['title']
    all_chapters = manga_info['chapters']
    
    print_colored(manga_title, Fore.BLUE)
    print_dim(f'{len(all_chapters)} chapters available')
    
    if not all_chapters:
        error(f"No chapters found for '{manga_slug}'")
    
    # Parse chapters to download
    if args.chapters:
        chapters_str = ' '.join(args.chapters)
        CHAPTERS = parse_chapter_intervals(chapters_str, all_chapters)
        # Filter only available chapters
        CHAPTERS = [ch for ch in CHAPTERS if ch in all_chapters]
    else:
        CHAPTERS = all_chapters
    
    if not CHAPTERS:
        error("No chapters found to download")
    
    print_dim(f'{len(CHAPTERS)} chapter{plural(len(CHAPTERS))} will be downloaded - Cancel with Ctrl+C')
    
    # Download chapters
    manga_encoded = encode(manga_title)
    
    for chapter in CHAPTERS:
        chapter_str = f'{chapter:g}'
        print_colored(f'Downloading {manga_title} {chapter_str}', Fore.YELLOW, Style.BRIGHT)
        
        image_urls = get_chapter_images(manga_slug, chapter)
        
        if not image_urls:
            print_colored(f'No images found for chapter {chapter_str}', Fore.RED)
            continue
        
        chapter_dir = chapter_directory(manga_encoded, chapter)
        
        for i, img_url in enumerate(image_urls, 1):
            # Determine extension from URL
            ext = 'jpg' if '.jpg' in img_url.lower() else 'png' if '.png' in img_url.lower() else 'webp'
            img_path = f'{chapter_dir}/{i}.{ext}'
            download_image(img_url, img_path, i, len(image_urls))
    
    # Close browser before conversion
    cleanup_browser()
    
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
                for ext in ['jpg', 'png', 'webp']:
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
