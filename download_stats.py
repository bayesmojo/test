import csv, os, re, time, zipfile
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
import requests
from bs4 import BeautifulSoup

BASE='https://master.get.com.tw/exam/List.aspx'
CATEGORY='164'
KEYWORD='統計'
OUT=Path('downloaded'); OUT.mkdir(exist_ok=True)
s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0','Accept-Language':'zh-TW,zh;q=0.9,en;q=0.7'})

def get(url, **kwargs):
    last=None
    for i in range(5):
        try:
            r=s.get(url,timeout=40,**kwargs)
            if r.status_code==200: return r
            last=RuntimeError(f'HTTP {r.status_code}: {url}')
        except Exception as e: last=e
        time.sleep(1.5*(i+1))
    raise last

def page_url(p): return f'{BASE}?iPageNo={p}&iDG={CATEGORY}'
def clean(x):
    x=re.sub(r'[\\/:*?"<>|\r\n\t]+','_',x); x=re.sub(r'\s+',' ',x).strip().strip('.')
    return x[:180] or 'paper'

r0=get(page_url(1)); r0.encoding=r0.apparent_encoding or 'utf-8'
t0=BeautifulSoup(r0.text,'html.parser').get_text(' ',strip=True)
m=re.search(r'共\s*([0-9,]+)\s*頁',t0)
if not m: raise RuntimeError('Cannot determine page count')
total=int(m.group(1).replace(',',''))
print('pages',total,flush=True)

matches=[]; seen=set()
for p in range(1,total+1):
    r=r0 if p==1 else get(page_url(p)); r.encoding=r.apparent_encoding or 'utf-8'; soup=BeautifulSoup(r.text,'html.parser')
    n=0
    for tr in soup.find_all('tr'):
        tds=tr.find_all('td'); link=tr.find('a',href=re.compile(r'Download\.ashx',re.I))
        if len(tds)<4 or not link: continue
        cells=[td.get_text(' ',strip=True) for td in tds]
        if len(cells)>=5: number,school,subject,year=cells[0],cells[1],cells[2],cells[3]
        else: continue
        if KEYWORD not in subject: continue
        href=urljoin(r.url,link.get('href'))
        if href in seen: continue
        seen.add(href); matches.append(dict(page=p,number=number,school=school,subject=subject,year=year,download_url=href)); n+=1
    if p%25==0 or n: print('scan',p,'/',total,'new',n,'total',len(matches),flush=True)
    time.sleep(.05)

if not matches: raise RuntimeError('No matching subjects found')
results=[]; failures=[]
for i,item in enumerate(matches,1):
    try:
        rr=get(item['download_url'],headers={'Referer':page_url(item['page']),'Accept':'application/pdf,*/*;q=0.8'},allow_redirects=True)
        data=rr.content; pos=data[:1024].find(b'%PDF')
        if pos<0: raise RuntimeError(f'Not PDF: {rr.headers.get("content-type","")} {rr.url} {len(data)} bytes')
        if pos: data=data[pos:]
        uid=parse_qs(urlparse(item['download_url']).query).get('iDP',[str(item['number'])])[0]
        path=OUT/clean(f"{item['year']}_{item['school']}_{item['subject']}_{uid}.pdf")
        k=2; base=path
        while path.exists(): path=OUT/f'{base.stem}_{k}.pdf'; k+=1
        path.write_bytes(data)
        rec=dict(item,filename=path.name,final_url=rr.url,bytes=len(data),status='ok'); results.append(rec)
        print(f'[{i}/{len(matches)}] OK',path.name,len(data),flush=True)
    except Exception as e:
        rec=dict(item,filename='',final_url='',bytes=0,status=f'ERROR: {e}'); failures.append(rec); print(f'[{i}/{len(matches)}] ERROR',e,flush=True)
    time.sleep(.08)

fields=['page','number','school','subject','year','download_url','filename','final_url','bytes','status']
with open('manifest.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); [w.writerow(x) for x in results+failures]
with open('summary.txt','w',encoding='utf-8') as f:
    f.write(f'Source iDG={CATEGORY}\nFilter: 考試科目 contains {KEYWORD}\nPages scanned: {total}\nMatching records: {len(matches)}\nPDFs downloaded: {len(results)}\nFailures: {len(failures)}\n')
zip_name='統計考古題_iDG164.zip'
with zipfile.ZipFile(zip_name,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in sorted(OUT.glob('*.pdf')): z.write(p,p.name)
    z.write('manifest.csv'); z.write('summary.txt')
print('created',zip_name,os.path.getsize(zip_name),'bytes',flush=True)
