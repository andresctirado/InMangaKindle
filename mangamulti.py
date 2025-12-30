#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""
MangaMulti Downloader - Download manga from mangamulti.com with language selection
Based on InMangaKindle by Carleslc

Usage:
    python3 mangamulti.py "blue-lock" --lang es --chapters 1..10 --format EPUB
    python3 mangamulti.py "one-piece" --lang en --chapters 1..5
    
Language options:
    --lang es      Spanish (default)
    --lang en      English
    
Requirements:
    pip install requests beautifulsoup4 colorama
"""

VERSION = '1.0'
NAME = 'MangaMultiKindle'

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

# MangaMulti URLs
PROVIDER_WEBSITE = "https://www.mangamulti.com"
CDN_BASE = "https://cdn.mangamulti.com/cdn"
MANGA_DIR = './manga'

# Language configuration
LANGUAGE_CONFIG = {
    'es': {
        'code': 'es',
        'name': 'Spanish',
        'cdn_path': 'ipfs2222es',
        'manga_suffix': '-es',
        'url_path': 'es',
    },
    'en': {
        'code': 'en', 
        'name': 'English',
        'cdn_path': 'ipfs2222',
        'manga_suffix': '',
        'url_path': 'en',
    },
}

CHAPTERS_FORMAT = 'Format: start..end or chapters with commas. Example: --chapters "1..10" will download chapters 1-10.'

def set_args():
    global args
    parser = argparse.ArgumentParser(prog=NAME, description='Download manga from MangaMulti with language selection')
    parser.add_argument("manga_name", help="manga name to download (e.g., 'blue-lock')")
    parser.add_argument("--lang", "--language", help="Language: es (Spanish), en (English)", 
                        default='es', choices=['es', 'en'])
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

def slugify(name):
    """Convert manga name to URL slug"""
    return re.sub(r'[^\w\-]+', '-', name.lower()).strip('-')

def clean_title(title):
    """Remove language suffix (ES, EN) from manga title for cleaner file/folder names"""
    # Remove common language suffixes
    cleaned = re.sub(r'\s+(ES|EN|es|en)$', '', title.strip())
    return cleaned

def check_chapter_exists(manga_slug, chapter_num, lang_config):
    """Check if a specific chapter exists and return True/False"""
    url_path = lang_config['url_path']
    manga_suffix = lang_config['manga_suffix']
    manga_url_slug = f"{manga_slug}{manga_suffix}"
    
    chapter_str = str(int(chapter_num)) if chapter_num == int(chapter_num) else str(chapter_num).replace('.', '-')
    url = f"{PROVIDER_WEBSITE}/{url_path}/{manga_url_slug}/{manga_url_slug}-chapter-{chapter_str}.html"
    
    try:
        response = requests.head(url, timeout=10)
        return response.status_code == 200
    except:
        return False

def get_manga_page(manga_slug, lang_config):
    """Get manga page and extract chapter list"""
    url_path = lang_config['url_path']
    manga_suffix = lang_config['manga_suffix']
    manga_url_slug = f"{manga_slug}{manga_suffix}"
    
    url = f"{PROVIDER_WEBSITE}/{url_path}/manga/{manga_url_slug}.html"
    print_dim(f'Fetching manga info from {url}...')
    
    try:
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            return None, None, manga_url_slug
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract manga title - try meta og:title first, then h1 with specific class, then fallback
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            manga_title = og_title['content']
            # Clean up common prefixes/suffixes
            manga_title = re.sub(r'^Read\s+', '', manga_title)
            manga_title = manga_title.split(' Manga')[0].strip()
            manga_title = manga_title.split(' Online')[0].strip()
        else:
            # Try to find a more specific h1 or h2 with the manga name
            title_elem = soup.find('h1', class_='entry-title') or soup.find('h2', class_='manga-title')
            if title_elem:
                manga_title = title_elem.get_text().strip()
            else:
                # Last fallback: use the formatted slug
                manga_title = manga_slug.replace('-', ' ').title()
                if manga_suffix:
                    manga_title += ' ' + manga_suffix.upper().replace('-', '')
        
        # Extract chapters from links
        # Pattern: /es/blue-lock-es/blue-lock-es-chapter-90.html or chapter-288-5.html for decimals
        chapters = set()
        chapter_pattern = re.compile(rf'/{url_path}/{manga_url_slug}/{manga_url_slug}-chapter-(\d+(?:-\d+)?).html')
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            match = chapter_pattern.search(href)
            if match:
                ch_str = match.group(1).replace('-', '.')
                chapters.add(float(ch_str))
        
        return manga_title, sorted(chapters), manga_url_slug
    
    except requests.RequestException:
        network_error()

def get_chapter_images(manga_slug, chapter_num, lang_config):
    """Get all image URLs for a specific chapter"""
    url_path = lang_config['url_path']
    manga_suffix = lang_config['manga_suffix']
    cdn_path = lang_config['cdn_path']
    manga_url_slug = f"{manga_slug}{manga_suffix}"
    
    # Format chapter number
    chapter_str = str(int(chapter_num)) if chapter_num == int(chapter_num) else str(chapter_num)
    
    url = f"{PROVIDER_WEBSITE}/{url_path}/{manga_url_slug}/{manga_url_slug}-chapter-{chapter_str}.html"
    print_dim(f'Fetching chapter {chapter_str} from {url}...')
    
    try:
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all images with data-src (lazy loaded) - use set to avoid duplicates
        images_set = set()
        for img in soup.find_all('img'):
            # Try data-src first (lazy loading), then src
            src = img.get('data-src') or img.get('src', '')
            
            # Filter for CDN manga images (support both .webp and .jpeg/.jpg)
            if 'cdn.mangamulti.com' in src:
                # Skip base64 placeholder images
                if src.startswith('data:'):
                    continue
                # Check for valid image extensions
                if any(ext in src.lower() for ext in ['.webp', '.jpeg', '.jpg', '.png']):
                    images_set.add(src)
        
        # Convert to sorted list (sort by page number in filename)
        def get_page_num(url):
            match = re.search(r'/(\d+)\.\w+$', url)
            return int(match.group(1)) if match else 0
        
        images = sorted(list(images_set), key=get_page_num)
        
        # If no images found via scraping, try to construct URLs from CDN pattern
        if not images:
            # Get manga title from URL for CDN path
            manga_title_cdn = manga_url_slug.replace('-', ' ').title().replace(' Es', ' ES')
            
            # Try different extensions: webp first, then jpeg
            for ext in ['webp', 'jpeg', 'jpg']:
                test_url = f"{CDN_BASE}/{cdn_path}/{requests.utils.quote(manga_title_cdn)}/Chapter%20{chapter_str}/001.{ext}"
                try:
                    test_response = requests.head(test_url, timeout=10)
                    if test_response.status_code == 200:
                        # Found the right extension, now get all pages
                        for i in range(1, 100):  # Increased max pages
                            page_url = f"{CDN_BASE}/{cdn_path}/{requests.utils.quote(manga_title_cdn)}/Chapter%20{chapter_str}/{i:03d}.{ext}"
                            check_response = requests.head(page_url, timeout=5)
                            if check_response.status_code == 200:
                                images.append(page_url)
                            elif i > 1:  # Stop after first missing page
                                break
                        break  # Found working extension, stop trying others
                except:
                    continue
        
        return images
    
    except requests.RequestException as e:
        print_colored(f'Error fetching chapter: {e}', Fore.RED)
        return []

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
    if not all_chapters:
        return []
    
    last = max(all_chapters)
    
    def parse_chapter(chapter):
        return last if chapter.strip() == 'last' else float(chapter.strip())
    
    chapters_to_download = set()
    
    for part in chapter_intervals_str.split(','):
        part = part.strip()
        if '..' in part:
            start, end = part.split('..')
            start_num = parse_chapter(start)
            end_num = parse_chapter(end)
            for ch in all_chapters:
                if start_num <= ch <= end_num:
                    chapters_to_download.add(ch)
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
    manga_name = args.manga_name.strip().lower()
    language = args.lang.lower()
    lang_config = LANGUAGE_CONFIG[language]
    
    print_colored(f"Language: {lang_config['name']}", Style.BRIGHT, Fore.CYAN)
    
    # Clean up manga name - convert to slug
    manga_slug = slugify(manga_name)
    
    # Remove common language suffixes if present
    manga_slug = re.sub(r'-es$', '', manga_slug)
    manga_slug = re.sub(r'-en$', '', manga_slug)
    
    print_colored(f"Searching '{manga_slug}' on MangaMulti...", Style.BRIGHT)
    
    # Get manga info
    manga_title, all_chapters, manga_url_slug = get_manga_page(manga_slug, lang_config)
    
    if not manga_title:
        error(f"Manga not found: '{manga_slug}'", 
              f"Try the full URL slug or check https://www.mangamulti.com/{lang_config['url_path']}/")
    
    print_colored(manga_title, Fore.BLUE, Style.BRIGHT)
    print_dim(f'{len(all_chapters)} chapter{plural(len(all_chapters))} listed on page (may be incomplete)')
    
    # Parse chapters to download
    if args.chapters:
        chapters_str = ' '.join(args.chapters)
        
        # Parse chapter numbers directly from user input
        requested_chapters = set()
        for part in chapters_str.split(','):
            part = part.strip()
            if '..' in part:
                start, end = part.split('..')
                start_num = float(start.strip())
                end_num = float(end.strip())
                # For ranges, use what we have in the list or generate the range
                if all_chapters:
                    for ch in all_chapters:
                        if start_num <= ch <= end_num:
                            requested_chapters.add(ch)
                # Also add the exact range values if not found
                for ch in range(int(start_num), int(end_num) + 1):
                    requested_chapters.add(float(ch))
            else:
                requested_chapters.add(float(part.strip()))
        
        # Verify each requested chapter exists
        CHAPTERS = []
        for ch in sorted(requested_chapters):
            if ch in all_chapters:
                CHAPTERS.append(ch)
            else:
                # Chapter not in visible list, check if it exists directly
                print_dim(f'Verifying chapter {ch:g}...')
                if check_chapter_exists(manga_slug, ch, lang_config):
                    print_colored(f'  Chapter {ch:g} found!', Fore.GREEN)
                    CHAPTERS.append(ch)
                else:
                    print_colored(f'  Chapter {ch:g} not found', Fore.YELLOW)
    else:
        CHAPTERS = all_chapters
    
    if not CHAPTERS:
        error("No chapters found to download")
    
    print_dim(f'{len(CHAPTERS)} chapter{plural(len(CHAPTERS))} will be downloaded - Cancel with Ctrl+C')
    
    # Download chapters - use clean title (without ES/EN suffix) for folder/file names
    manga_title_clean = clean_title(manga_title)
    manga_encoded = encode(manga_title_clean)
    
    for chapter in CHAPTERS:
        chapter_str = f'{chapter:g}'
        print_colored(f'Downloading {manga_title_clean} Chapter {chapter_str}', Fore.YELLOW, Style.BRIGHT)
        
        image_urls = get_chapter_images(manga_slug, chapter, lang_config)
        
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
                for ext in ['jpg', 'png', 'webp']:
                    for name, path in sorted(files(chapter_dir, ext), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
                        page_paths.append(path)
                
                if page_paths:
                    path = f'{MANGA_DIR}/{manga_title_clean} {chapter:g}{extension}'
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
                    title = f'{manga_title_clean} {chapter_interval}'
                    print_colored(title, Fore.BLUE)
                    argv_full = argv + ['--title', title, temp]
                    manga2ebook(argv_full)
                    path = f'{MANGA_DIR}/{manga_title_clean} {chapter_interval}{extension}'
                    temp_output = f'{MANGA_DIR}/{os.path.basename(temp)}{extension}'
                    if os.path.exists(temp_output):
                        os.rename(temp_output, path)
                        print_colored(f'DONE: {os.path.abspath(path)}', Fore.GREEN, Style.BRIGHT)
            else:
                for chapter in CHAPTERS:
                    title = f'{manga_title_clean} {chapter:g}'
                    print_colored(title, Fore.BLUE)
                    chapter_dir = chapter_directory(manga_encoded, chapter)
                    argv_chapter = argv + ['--title', title, chapter_dir]
                    try:
                        manga2ebook(argv_chapter)
                        path = f'{MANGA_DIR}/{manga_title_clean} {chapter:g}{extension}'
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
