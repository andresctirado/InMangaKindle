#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""
TvyManga Downloader - Download manga from tvymanga3.com
Based on InMangaKindle by Carleslc

Usage:
    python3 tvymanga.py "one-piece" --chapters 1170 --format EPUB
    
Requirements:
    pip install playwright beautifulsoup4 colorama img2pdf
    playwright install chromium
    pip install kindlecomicconverter (for EPUB/MOBI/CBZ)
"""

VERSION = '1.0'
NAME = 'TvyMangaKindle'

import os
import re
import sys
import signal
import argparse
import tempfile
import time
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

import requests

# TvyManga URLs
PROVIDER_WEBSITE = "https://tvymanga3.com"

MANGA_DIR = './manga'

CHAPTERS_FORMAT = 'Format: start..end or chapters with commas. Example: --chapters "1170..1175" will download chapters 1170-1175.'

# Browser management
_playwright = None
_browser = None
_context = None

def get_browser():
    global _playwright, _browser, _context
    if _browser is None:
        print_dim('Starting browser...')
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(headless=True)
        _context = _browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
    return _context

def cleanup_browser():
    global _playwright, _browser, _context
    if _context:
        _context.close()
        _context = None
    if _browser:
        _browser.close()
        _browser = None
    if _playwright:
        _playwright.stop()
        _playwright = None

def set_args():
    global args
    parser = argparse.ArgumentParser(prog=NAME, description='Download manga from TvyManga')
    parser.add_argument("manga_slug", help="manga slug to download (e.g., 'one-piece')")
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

def download_image_with_session(url, path, page_num, total_pages, session):
    """Download a single image using requests session with cookies"""
    if os.path.isfile(path):
        print_colored(f'Page {page_num}/{total_pages} - Already exists', Fore.YELLOW)
        return True
    
    try:
        response = session.get(url, timeout=30)
        if response.status_code == 200:
            # Verify it's actually an image
            content_type = response.headers.get('Content-Type', '')
            if 'image' in content_type or len(response.content) > 1000:
                write_file(path, response.content)
                print_colored(f'Page {page_num}/{total_pages} ({100*page_num//total_pages}%)', Fore.GREEN)
                return True
            else:
                print_colored(f'Page {page_num}/{total_pages} - Not an image', Fore.RED)
                return False
        else:
            print_colored(f'Page {page_num}/{total_pages} - Failed ({response.status_code})', Fore.RED)
            return False
    except Exception as e:
        print_colored(f'Page {page_num}/{total_pages} - Error: {e}', Fore.RED)
        return False

def get_chapter_images_with_browser(manga_slug, chapter_num):
    """Get all image URLs for a specific chapter using browser to bypass anti-bot"""
    # URL pattern: https://tvymanga3.com/{manga-slug}-{chapter}/
    url = f"{PROVIDER_WEBSITE}/{manga_slug}-{chapter_num}/"
    print_dim(f'Fetching images from {url}...')
    
    try:
        context = get_browser()
        page = context.new_page()
        
        # Navigate and wait for content
        page.goto(url, wait_until='domcontentloaded')
        
        # Wait for images to load (scroll to trigger lazy load)
        page.wait_for_timeout(2000)
        
        # Scroll down to load all lazy images
        for _ in range(5):
            page.evaluate("window.scrollBy(0, 1000)")
            page.wait_for_timeout(500)
        
        # Scroll back to top
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)
        
        # Get all images from entry-content
        image_urls = page.evaluate('''() => {
            const container = document.querySelector('.entry-content') || document.querySelector('article') || document.body;
            const images = container.querySelectorAll('img');
            const urls = [];
            
            images.forEach(img => {
                const src = img.src || img.getAttribute('data-src') || img.getAttribute('data-lazy-src');
                if (src && !src.includes('logo') && !src.includes('banner') && !src.includes('avatar') && !src.includes('icon')) {
                    // Check if it looks like a manga image
                    if (src.includes('imgur') || src.includes('wp-content') || img.naturalHeight > 500 || img.height > 500) {
                        urls.push(src);
                    }
                }
            });
            
            return urls;
        }''')
        
        # Get cookies for downloading
        cookies = context.cookies()
        
        page.close()
        
        # Create session with cookies
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': url,
        })
        for cookie in cookies:
            session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain', ''))
        
        # Remove duplicates while preserving order
        seen = set()
        unique_images = []
        for img in image_urls:
            if img not in seen:
                seen.add(img)
                unique_images.append(img)
        
        return unique_images, session
    
    except Exception as e:
        print_colored(f'Error fetching chapter: {e}', Fore.RED)
        return [], None

def get_manga_title(manga_slug):
    """Try to get the proper manga title from the main page"""
    # Fallback: convert slug to title
    return manga_slug.replace('-', ' ').title()

def parse_chapter_list(chapters_str):
    """Parse chapter range string into list of chapter numbers"""
    chapters_to_download = []
    
    for part in chapters_str.split(','):
        part = part.strip()
        if '..' in part:
            start, end = part.split('..')
            start_num = int(start.strip())
            end_num = int(end.strip())
            chapters_to_download.extend(range(start_num, end_num + 1))
        else:
            chapters_to_download.append(int(part))
    
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
                intervals.append(str(start))
            else:
                intervals.append(f'{start}{start_end_sep}{end}')
            start = end = ch
    
    if start == end:
        intervals.append(str(start))
    else:
        intervals.append(f'{start}{start_end_sep}{end}')
    
    return interval_sep.join(intervals)


if __name__ == "__main__":
    cancellable()
    freeze_support()
    init_console_colors()
    
    set_args()
    
    MANGA_DIR = strip_path(args.directory, set(['_', '-', ' ', '.', '/']))
    manga_slug = args.manga_slug.strip().lower()
    
    # Remove URL if provided, extract just slug
    if 'tvymanga' in manga_slug:
        match = re.search(r'tvymanga\d*\.com/([^/]+?)(?:-\d+)?/?$', manga_slug)
        if match:
            manga_slug = match.group(1)
    
    print_colored(f"Preparing to download '{manga_slug}' from TvyManga...", Style.BRIGHT)
    
    # Get manga title
    manga_title = get_manga_title(manga_slug)
    print_colored(manga_title, Fore.BLUE)
    
    # Parse chapters to download
    if not args.chapters:
        error("Please specify chapters to download with --chapters", CHAPTERS_FORMAT)
    
    chapters_str = ' '.join(args.chapters)
    CHAPTERS = parse_chapter_list(chapters_str)
    
    if not CHAPTERS:
        error("No chapters specified to download")
    
    print_dim(f'{len(CHAPTERS)} chapter{plural(len(CHAPTERS))} will be downloaded - Cancel with Ctrl+C')
    
    # Download chapters
    manga_encoded = encode(manga_title)
    
    for chapter in CHAPTERS:
        print_colored(f'Downloading {manga_title} {chapter}', Fore.YELLOW, Style.BRIGHT)
        
        image_urls, session = get_chapter_images_with_browser(manga_slug, chapter)
        
        if not image_urls:
            print_colored(f'No images found for chapter {chapter}', Fore.RED)
            continue
        
        print_dim(f'Found {len(image_urls)} images')
        
        chapter_dir = chapter_directory(manga_encoded, float(chapter))
        
        for i, img_url in enumerate(image_urls, 1):
            # Determine extension from URL
            if '.jpg' in img_url.lower() or '.jpeg' in img_url.lower():
                ext = 'jpg'
            elif '.png' in img_url.lower():
                ext = 'png'
            elif '.webp' in img_url.lower():
                ext = 'webp'
            else:
                ext = 'jpg'  # Default
            
            img_path = f'{chapter_dir}/{i}.{ext}'
            download_image_with_session(img_url, img_path, i, len(image_urls), session)
    
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
                chapter_dir = chapter_directory(manga_encoded, float(chapter))
                page_paths = []
                for ext in ['jpg', 'jpeg', 'png', 'webp']:
                    for name, path in sorted(files(chapter_dir, ext), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
                        page_paths.append(path)
                
                if page_paths:
                    path = f'{MANGA_DIR}/{manga_title} {chapter}{extension}'
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
                    copy_all([(str(ch), chapter_directory(manga_encoded, float(ch))) for ch in CHAPTERS], temp)
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
                    title = f'{manga_title} {chapter}'
                    print_colored(title, Fore.BLUE)
                    chapter_dir = chapter_directory(manga_encoded, float(chapter))
                    argv_chapter = argv + ['--title', title, chapter_dir]
                    try:
                        manga2ebook(argv_chapter)
                        path = f'{MANGA_DIR}/{manga_title} {chapter}{extension}'
                        temp_output = f'{MANGA_DIR}/{float(chapter):g}{extension}'
                        if os.path.exists(temp_output):
                            os.rename(temp_output, path)
                        print_colored(f'DONE: {os.path.abspath(path)}', Fore.GREEN, Style.BRIGHT)
                    except Exception as e:
                        print_colored(f'Conversion error for chapter {chapter}: {e}', Fore.RED)
    else:
        chapter_interval = chapters_to_intervals_string(CHAPTERS, interval_sep=', ')
        directory = os.path.abspath(manga_directory(manga_encoded))
        print_colored(f'DONE: {directory} ({chapter_interval})', Fore.GREEN, Style.BRIGHT)
