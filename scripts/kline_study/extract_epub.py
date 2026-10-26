"""把 epub 解成纯文本(保留图片位置标记), 供学习笔记用. 只读源文件.
用法: python -I extract_epub.py <epub> <outdir>
"""
import sys, zipfile, os, re
from bs4 import BeautifulSoup


def norm(p):
    return os.path.normpath(p).replace(os.sep, '/')


def main(epub, outdir):
    os.makedirs(outdir, exist_ok=True)
    z = zipfile.ZipFile(epub)
    names = z.namelist()
    opf = [n for n in names if n.endswith('.opf')][0]
    soup = BeautifulSoup(z.read(opf), 'xml')
    base = os.path.dirname(opf)
    manifest = {i['id']: i['href'] for i in soup.find_all('item')}
    spine = [manifest[i['idref']] for i in soup.find_all('itemref') if i['idref'] in manifest]
    out = []
    for href in spine:
        p = norm(os.path.join(base, href))
        if p not in names:
            continue
        h = BeautifulSoup(z.read(p), 'html.parser')
        for img in h.find_all(['img', 'image']):
            src = img.get('src') or img.get('xlink:href') or img.get('href') or ''
            img.replace_with(f"\n[IMG {norm(os.path.join(os.path.dirname(p), src))}]\n")
        txt = h.get_text('\n')
        txt = re.sub(r'\n\s*\n+', '\n', txt)
        out.append(f"\n===== {href} =====\n" + txt)
    with open(os.path.join(outdir, 'full.txt'), 'w', encoding='utf-8') as f:
        f.write(''.join(out))
    imgdir = os.path.join(outdir, 'img')
    os.makedirs(imgdir, exist_ok=True)
    for n in names:
        if re.search(r'\.(jpe?g|png|gif|bmp)$', n, re.I):
            dst = os.path.join(imgdir, n.replace('/', '__'))
            with open(dst, 'wb') as f:
                f.write(z.read(n))
    print(outdir, len(''.join(out)), 'chars')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
