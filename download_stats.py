import csv, os, re, time, zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
import requests
from bs4 import BeautifulSoup

BASE='https://master.get.com.tw/exam/List.aspx'; CATEGORY='164'; KEYWORD='統計'
HEAD={'User-Agent':'Mozilla/5.0','Accept-Language':'zh-TW,zh;q=0.9,en;q=0.7'}
OUT=Path('downloaded'); OUT.mkdir(exist_ok=True)

def page_url(p): return f'{BASE}?iPageNo={p}&iDG={CATEGORY}'
def get(url, **kw):
    last=None
    for i in range(4):
        try:
            r=requests.get(url,headers={**HEAD,**kw.pop('headers',{})},timeout=25,**kw)
            if r.status_code==200: return r
            last=RuntimeError(f'HTTP {r.status_code}: {url}')
        except Exception as e: last=e
        time.sleep(.6*(i+1))
    raise last

def parse_page(p):
    r=get(page_url(p)); r.encoding=r.apparent_encoding or 'utf-8'; soup=BeautifulSoup(r.text,'html.parser'); out=[]
    for tr in soup.find_all('tr'):
        tds=tr.find_all('td'); a=tr.find('a',href=re.compile(r'Download\.ashx',re.I))
        if len(tds)<5 or not a: continue
        c=[x.get_text(' ',strip=True) for x in tds]
        number,school,subject,year=c[0],c[1],c[2],c[3]
        if KEYWORD in subject:
            out.append(dict(page=p,number=number,school=school,subject=subject,year=year,download_url=urljoin(r.url,a.get('href'))))
    return out

def clean(x):
    x=re.sub(r'[\\/:*?"<>|\r\n\t]+','_',x); x=re.sub(r'\s+',' ',x).strip().strip('.')
    return x[:180] or 'paper'

r=get(page_url(1)); r.encoding=r.apparent_encoding or 'utf-8'; text=BeautifulSoup(r.text,'html.parser').get_text(' ',strip=True)
m=re.search(r'共\s*([0-9,]+)\s*頁',text)
if not m: raise RuntimeError('Cannot determine page count')
total=int(m.group(1).replace(',','')); print('category pages',total,flush=True)

matches=[]
with ThreadPoolExecutor(max_workers=10) as ex:
    fut={ex.submit(parse_page,p):p for p in range(1,total+1)}
    done=0
    for f in as_completed(fut):
        p=fut[f]; rows=f.result(); matches.extend(rows); done+=1
        if rows or done%50==0: print('pages done',done,'/',total,'page',p,'new',len(rows),'total matches',len(matches),flush=True)
# exact category pages make this authoritative; de-duplicate download handlers
uniq={x['download_url']:x for x in matches}; matches=sorted(uniq.values(),key=lambda x:(x['page'],x['number']))
if not matches: raise RuntimeError('No matching subjects found')
print('matching records',len(matches),flush=True)

def download(item):
    rr=get(item['download_url'],headers={'Referer':page_url(item['page']),'Accept':'application/pdf,*/*;q=0.8'},allow_redirects=True)
    data=rr.content; pos=data[:1024].find(b'%PDF')
    if pos<0: raise RuntimeError(f'Not PDF: {rr.headers.get("content-type","")} {rr.url} {len(data)} bytes')
    if pos: data=data[pos:]
    uid=parse_qs(urlparse(item['download_url']).query).get('iDP',[str(item['number'])])[0]
    name=clean(f"{item['year']}_{item['school']}_{item['subject']}_{uid}.pdf")
    return item,name,rr.url,data

results=[]; failures=[]
with ThreadPoolExecutor(max_workers=6) as ex:
    fut={ex.submit(download,x):x for x in matches}; done=0
    for f in as_completed(fut):
        item=fut[f]; done+=1
        try:
            item,name,final,data=f.result(); path=OUT/name
            if path.exists(): path=OUT/clean(f"{path.stem}_{item['number']}.pdf")
            path.write_bytes(data); results.append(dict(item,filename=path.name,final_url=final,bytes=len(data),status='ok'))
        except Exception as e:
            failures.append(dict(item,filename='',final_url='',bytes=0,status=f'ERROR: {e}'))
        if done%10==0 or done==len(matches): print('downloads',done,'/',len(matches),'ok',len(results),'fail',len(failures),flush=True)

fields=['page','number','school','subject','year','download_url','filename','final_url','bytes','status']
with open('manifest.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(results+failures)
with open('summary.txt','w',encoding='utf-8') as f:
    f.write(f'Source category iDG={CATEGORY}\nFilter: 考試科目 contains {KEYWORD}\nCategory pages scanned: {total}\nMatching records: {len(matches)}\nPDFs downloaded: {len(results)}\nFailures: {len(failures)}\n')
zip_name='統計考古題_iDG164.zip'
with zipfile.ZipFile(zip_name,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
    for p in sorted(OUT.glob('*.pdf')): z.write(p,p.name)
    z.write('manifest.csv'); z.write('summary.txt')
print('created',zip_name,os.path.getsize(zip_name),'bytes; failures',len(failures),flush=True)
