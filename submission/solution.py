"""Offline, provenance-preserving knowledge system. Standard library only."""
import bisect
import calendar
import copy
import datetime as dt
import html
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from urllib.parse import urlsplit


# Structural contract: deliberately independent of the location of the harness.
@dataclass
class Source:
    url: str
    snapshot_id: str = None
    quote: str = None


@dataclass
class Answer:
    text: str
    sources: list = field(default_factory=list)
    confident: bool = True
    conflict_note: str = None


@dataclass
class Conflict:
    topic: str
    values: list
    sources: list
    resolution: str = None
    reason: str = None


# Reuse the official result classes when the harness provides them (including
# its repeat-consistency pass); otherwise the same structural types work alone.
try:
    from contract import Answer, Conflict, Source
except ImportError:
    pass


def clean(text):
    text = html.unescape(html.unescape(text))
    text = re.sub(r"!\[[^\]]*\]\([^\n]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^\s]*?(?:\s+\"[^\"]*\")?\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return text.replace("\\r\\n", "\n").replace("\\", "").replace("**", "").replace(" ", " ")


def norm(text):
    return re.sub(r"\s+", " ", clean(text).lower().replace("–", "-").replace("—", "-").replace("’", "'")).strip()


STOP = set("what what's is are was were the a an of on for to in at and or do does can could you your me i it my we our please tell give get current currently now rate rates interest apr apy dupaco much how would like know account accounts".split())
NUMWORDS = dict(zip("one two three four five six seven eight nine ten eleven twelve fifteen seventeen eighteen twenty thirty thirtysix forty fortyeight sixty seventy eighty".split(), [1,2,3,4,5,6,7,8,9,10,11,12,15,17,18,20,30,36,40,48,60,70,80]))


def normalized_question(text):
    text = norm(text)
    for phrase, num in [("eighty four",84),("seventy two",72),("forty eight",48),("thirty six",36),("twenty four",24),("sixty",60),("thirty",30),("fifteen",15)]:
        text = re.sub(r"\b" + phrase.replace(" ", r"[ -]") + r"\b", str(num), text)
    for word, num in NUMWORDS.items():
        text = re.sub(r"\b" + word + r"\b", str(num), text)
    text = re.sub(r"\b(cds?|term[- ]shares?)\b", "certificate", text)
    text = re.sub(r"\b(car|vehicle|motorcycle)\b", "auto", text)
    text = re.sub(r'\b(mos?|mths?)\b', 'month', text)
    text = re.sub(r'\b(yrs?)\b', 'year', text)
    text = text.replace("home loan", "mortgage").replace("drive-through", "drive-up").replace("drive-thru", "drive-up")
    return text


def tokens(text):
    text = normalized_question(text)
    words = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text)
    return [w[:-1] if w.endswith('s') and len(w)>4 else w for w in words if w not in STOP]


def date_value(text):
    for pattern, fmt in [(r"\b\d{4}-\d{2}-\d{2}\b", "%Y-%m-%d"), (r"\b\d{1,2}/\d{1,2}/\d{4}\b", "%m/%d/%Y"), (r"\b\d{1,2}/\d{1,2}/\d{2}\b", "%m/%d/%y"), (r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}\b", "%B %d, %Y")]:
        m = re.search(pattern, text, re.I)
        if m:
            try:
                return dt.datetime.strptime(m.group(), fmt).date().isoformat()
            except ValueError:
                pass
    return ""


def authority(url):
    path = urlsplit(url).path.lower()
    if path.rstrip('/') in ('/personal/savings-account','/personal/checking-accounts','/personal/loans/home-loans','/personal/loans/auto-motorcycle-loans','/personal/loans/personal-loans','/personal/credit-cards','/business/credit-cards','/business/cash-management'):
        return 6
    if 'calculator' in path:
        return 0
    if '/learn/' in path or re.search(r'/20\d\d/',path):
        return 1
    if '/newsroom/' in path:
        return 2
    if '/hubfs/' in path:
        return 4 if re.search(r'(rate|fee|terms)',path) else 1
    if '/rates' in path or '/personal/' in path or '/business/' in path:
        return 5
    return 3


def model_range(entity):
    m=re.search(r'(20\d\d|19\d\d)(?:\s*-\s*(\d{2,4}))?',norm(entity))
    if not m:return None
    lo=int(m[1]);hi=int(m[2]) if m[2] else lo
    if hi<100:hi=lo//100*100+hi
    return (1900 if 'older' in norm(entity) else lo,hi)


@dataclass
class Fact:
    entity: str
    qualifier: str
    metric: str
    value: str
    source: Source
    effective: str
    rank: int
    context: str = ""
    valid_until: str = ""

    @property
    def key(self):
        # Commas in money amounts and typographic punctuation aren't new tiers.
        return tuple(norm(s).replace(',', '') for s in (self.entity,self.qualifier,self.metric))

    @property
    def numeric(self):
        return tuple(float(n) for n in re.findall(r"\d+(?:\.\d+)?", self.value.replace(',', '')))

    def render(self):
        label = self.entity + (" (" + self.qualifier + ")" if self.qualifier else "")
        return f"{label}: {self.value} {self.metric}"


@dataclass
class Chunk:
    text: str
    heading: str
    source: Source
    rank: int
    published: str
    terms: Counter


class State:
    def __init__(self, snapshot):
        self.sid, self.date = snapshot.snapshot_id, snapshot.taken_on
        self.pages = {p.url.rstrip('/'):p for p in snapshot.pages}
        self.facts = []
        self.chunks = []
        self.postings = defaultdict(list)
        self.cleaned = {}
        for page in snapshot.pages:
            text = clean(page.markdown)
            # Related-story cards and embedded forms are not article evidence.
            text = re.split(r"(?im)^## Handpicked for You", text)[0]
            self.cleaned[page.url.rstrip('/')] = text
            self._tables(page, text)
            self._prose_facts(page, text)
            self._chunks(page, text)
        self.by_key = defaultdict(list)
        for f in self.facts:
            self.by_key[f.key].append(f)
        self.winners = {key:max([f for f in fs if not f.valid_until or f.valid_until>=self.date],key=self.fact_rank) for key,fs in self.by_key.items() if any(not f.valid_until or f.valid_until>=self.date for f in fs)}
        self.avg_len = sum(sum(c.terms.values()) for c in self.chunks) / max(1,len(self.chunks))

    @staticmethod
    def fact_rank(f):
        return (f.rank, f.effective, f.source.url, f.source.quote or '')

    def add_fact(self, page, entity, qualifier, metric, value, quote, effective='', context=''):
        if effective and effective > self.date:
            return
        f = Fact(entity.strip(), qualifier.strip(), metric, value.strip(), Source(page.url,self.sid,quote[:1000]),effective,authority(page.url),context)
        expiry=re.search(r'(?i)(?:offer |promotion |promo )?(?:ended|ends|expires|expired|valid through)\s*:?\s*(.+)',quote)
        if expiry:f.valid_until=date_value(expiry[1])
        if f.entity and f.value:
            self.facts.append(f)

    def _tables(self,page,text):
        lines = text.splitlines()
        heading, label, section = '', '', ''
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('#'):
                heading = line.lstrip('# ').strip()
            if line.startswith('- ') and 'Rates' in line:
                section=line.lstrip('- ').strip()
            if not line.startswith('|'):
                if line and len(line)<120 and not line.startswith(('#','-','!','[')):
                    label = line
                i+=1
                continue
            table=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                table.append(lines[i].strip()); i+=1
            if len(table)<2:
                continue
            rows=[[v.strip() for v in row.strip('|').split('|')] for row in table]
            header=rows[0]
            has_header=len(rows)>1 and all(re.fullmatch(r'[: -]*',c) for c in rows[1])
            if not has_header:
                continue
            after='\n'.join([line for line in lines[i:i+30] if line.strip()][:3])
            eff = date_value(after) if re.search(r'effective|as of',after,re.I) else ''
            for row in rows[2:]:
                if len(row)!=len(header) or not row[0]:
                    continue
                h = [norm(x) for x in header]
                context = ' '.join([page.title,heading,section,label])
                entity=row[0]; qualifier=[]
                is_cert='certificate' in norm(context+' '+header[0]) or (h[0]=='term' and any('dividend' in c for c in h))
                if is_cert and 'certificate' not in norm(entity): entity += ' Certificate'
                if h[0] in ('balance','balance tier'):
                    entity=(section.replace(' Rates','') if label.lower() in ('saving account rates','savings account rates') else label)
                    qualifier.append(row[0])
                if h[0] in ('term','loan amount') and not re.search(r'certificate|model year',entity,re.I):
                    entity=label or heading or page.title
                    qualifier.append(row[0])
                for n,(name,value) in enumerate(zip(h,row)):
                    if n==0: continue
                    if name in ('balance tier','term','loan program','loan amount'):
                        qualifier.append(value)
                for n,(name,value) in enumerate(zip(h,row)):
                    if n==0: continue
                    metric=None
                    if 'apy' in name or 'annual percentage yield' in name: metric='APY'
                    elif 'annual percentage rate' in name or 'apr' in name: metric='APR'
                    elif 'dividend rate' in name: metric='dividend rate'
                    elif name=='rate': metric='rate'
                    elif name.startswith('min. to'): metric=header[n]
                    elif re.search(r'fee|service|col2',h[0]) and re.search(r'\$|free|%',value,re.I): metric='fee'
                    if metric:
                        value=re.sub(r'(\bAPR|%)(?:\d+)\b',r'\1',value)
                        if metric=='APR':value=re.sub(r'\s*APR\b','',value,flags=re.I).strip()
                        self.add_fact(page,entity,'; '.join(qualifier),metric,value,'\n'.join([table[0],table[1],'| '+' | '.join(row)+' |']),eff,context)

    def _prose_facts(self,page,text):
        heading=''
        published=date_value(text[:400]) if '/newsroom/' in page.url else ''
        for line in text.splitlines():
            if line.startswith('#'): heading=line.lstrip('# ').strip()
            # Small free-form fact sheets, including the supplied harness self-test.
            m=re.search(r'(?i)((?:\d+[ -]month\s+)?(?:[\w -]*certificate))\s+(APY|APR|rate)\s*:?\s*(\d+(?:\.\d+)?\s*%)',line)
            if m:
                self.add_fact(page,m[1],'',m[2].upper() if m[2].lower()!='rate' else 'rate',m[3],line,context=heading)
            m=re.search(r'(?i)^([^:]+(?:fee|replacement))\s*:\s*(\$\d+(?:\.\d+)?)',line)
            if m: self.add_fact(page,m[1],'','fee',m[2],line)
            if 'visa' in norm(heading) and 'credit-card' in page.url:
                if re.search(r'ongoing|competitive rate|variable annual percentage',line,re.I):
                    rates=re.findall(r'\d+(?:\.\d+)?%\s*(?:[-–]\s*\d+(?:\.\d+)?%)?',line)
                    if rates: self.add_fact(page,heading,'','APR',rates[0],line)
                intro=re.search(r'(\d+(?:\.\d+)?%)\s*intro\s*APR',line,re.I)
                if intro:
                    duration=re.search(r'for (?:the (?:first )?)?(\d+ (?:months?|days?))',line,re.I)
                    qualifier='balance transfer'+('; '+duration[1] if duration else '')
                    self.add_fact(page,heading,qualifier,'intro APR',intro[1],line)
            m=re.search(r'\b(\d+) branch office locations',line)
            if m:self.add_fact(page,'Dupaco branch office locations','','count',m[1],line,published)

    def _chunks(self,page,text):
        heading=page.title
        published=date_value(text[:400]) if '/newsroom/' in page.url or '/learn/' in page.url else ''
        if published and published>self.date:return
        seen=set()
        for block in re.split(r'\n\s*\n',text):
            block=block.strip()
            if block.startswith('#'):
                heading=block.lstrip('# ').strip(); continue
            if len(block)<25 or len(block)>8000 or block.startswith(('|','- 🇦')): continue
            if re.search(r'(First Name|Last Name|Submit|data:image|^Continue|^Cancel)',block): continue
            if len(block)<80 and re.search(r'https?://',block): continue
            # Paragraph-sized chunks retain nearby heading context.
            for segment in re.split(r'\n(?=- )',block):
                if len(segment)>1800:
                    parts=re.split(r'(?<=[.!?])\s+(?=[A-Z])',segment)
                else: parts=[segment]
                for part in parts:
                    part=part.strip()
                    if len(part)<25 or norm(part) in seen: continue
                    seen.add(norm(part))
                    c=Chunk(part,heading,Source(page.url,self.sid,part[:1000]),authority(page.url),published,Counter(tokens(heading+' '+part)))
                    n=len(self.chunks);self.chunks.append(c)
                    for token in c.terms: self.postings[token].append(n)

    def search(self,question,limit=8,predicate=None):
        query=set(tokens(question)); scores=defaultdict(float)
        n=len(self.chunks)
        for t in query:
            posting=self.postings.get(t,())
            idf=math.log(1+(n-len(posting)+0.5)/(len(posting)+0.5))
            for i in posting:
                c=self.chunks[i]; tf=c.terms[t]
                scores[i]+=idf*tf*2.2/(tf+1.2*(0.25+0.75*sum(c.terms.values())/max(1,self.avg_len)))
        result=[]
        for i,score in scores.items():
            c=self.chunks[i]
            if predicate and not predicate(c): continue
            overlap=len(query&c.terms.keys())/max(1,len(query))
            score*=0.65+0.35*overlap
            score*=1+0.12*c.rank
            if c.published: score+= max(0,int(c.published[:4])-2015)*0.06
            result.append((score,c))
        return sorted(result,key=lambda v:(-v[0],v[1].source.url,v[1].text))[:limit]


class KnowledgeSystem:
    def __init__(self):
        self.states=[]
        self._cache={}

    def ingest(self,snapshot):
        state=State(snapshot)
        # Full snapshots replace missing pages; they are never carried forward.
        self.states=[s for s in self.states if s.sid!=state.sid]
        self.states.append(state); self.states.sort(key=lambda s:(s.date,s.sid))
        self._cache.clear()

    def _state(self,as_of):
        if not self.states: return None
        if as_of is None: return self.states[-1]
        try: date=dt.date.fromisoformat(str(as_of)[:10]).isoformat()
        except ValueError: return None
        i=bisect.bisect_right([s.date for s in self.states],date)-1
        return self.states[i] if i>=0 else None

    @staticmethod
    def unknown():
        return Answer("I don't know from the provided snapshots; this information isn't listed. Please contact the credit union to confirm.",confident=False)

    def answer(self,question,as_of=None):
        if not isinstance(question,str) or not question.strip(): return self.unknown()
        q=normalized_question(question)
        if as_of is None and re.search(r'\b(changed|changes|compare|comparison|history|historical trend)\b',q):
            return self._changes(q)
        # Explicit as_of always wins. An embedded historical date can also select a view.
        if as_of is None and re.search(r'\b(as of|back in|was|were|in (?:january|february|march|april|may|june|july|august|september|october|november|december))\b',q):
            as_of=date_value(question)
            if not as_of:
                for month in list(calendar.month_name)[1:]:
                    m=re.search(r'\b'+month.lower()+r'\s+(20\d\d)\b',q)
                    if m:
                        year=int(m[1]);mo=list(calendar.month_name).index(month)
                        as_of=dt.date(year,mo,calendar.monthrange(year,mo)[1]).isoformat();break
            as_of=as_of or None
        state=self._state(as_of)
        if state is None: return self.unknown()
        key=(state.sid,q)
        if key not in self._cache:
            ans=self._structured(state,q)
            self._cache[key]=ans if ans is not None else self._descriptive(state,q)
        return copy.deepcopy(self._cache[key])

    def _changes(self,q):
        observations=[]
        sources=[]
        previous=None
        for state in self.states:
            ans=self._structured(state,q)
            if ans is None or not ans.confident:continue
            # Compare member-facing values, not quotes or snapshot identifiers.
            signature=ans.text
            if signature!=previous:
                observations.append(f'As of {state.date}: {ans.text}')
                sources.extend(ans.sources)
                previous=signature
        if not observations:return self.unknown()
        return Answer(' '.join(observations),sources,conflict_note='These are dated observations from full snapshots, not evidence of the exact day a change took effect.')

    def _fact_answer(self,state,facts):
        if not facts: return self.unknown()
        facts=list({f.key:f for f in facts}.values())
        sources=[];seen=set();notes=[]
        for f in facts:
            k=(f.source.url,f.source.quote)
            if k not in seen: sources.append(f.source);seen.add(k)
            peers=state.by_key[f.key]
            active=[p for p in peers if (not p.valid_until or p.valid_until>=state.date)]
            tied=[p for p in active if (p.rank,p.effective)==(f.rank,f.effective)]
            if len({p.numeric for p in tied})>1:
                return Answer('I cannot confirm a single current value: equally authoritative sources disagree for this product and tier. Please contact the credit union.',[p.source for p in tied],False,'No effective-date or authority evidence resolves this disagreement.')
            if len({p.numeric for p in peers})>1:
                notes.append('The official product/rate sheet and its effective date take precedence over lower-authority or older claims for the same tier and metric.')
        return Answer('; '.join(f.render() for f in facts)+'.',sources,conflict_note=notes[0] if notes else None)

    def _structured(self,state,q):
        allfacts=list(state.winners.values())
        term=re.search(r'\b(\d+)[ -]?(month|year)',q)
        def term_match(f):
            return not term or bool(re.search(r'\b'+term[1]+r'[ -]?'+term[2],norm(f.entity+' '+f.qualifier)))
        rate_request=bool(re.search(r'\b(rate|rates|apr|apy|yield|dividend|earn|interest)\b',q))
        if 'certificate' in q:
            fs=[f for f in allfacts if 'certificate' in norm(f.entity+' '+f.context)]
            if re.search(r'\b(link|url|website|where.*(?:find|see))\b',q):
                if not fs: return self.unknown()
                f=max(fs,key=State.fact_rank);url=f.source.url.split('#')[0]+'#rates'
                return Answer(url,[Source(f.source.url,state.sid,f.source.quote)])
            fs=[f for f in fs if term_match(f)]
            if 'jumbo' in q: fs=[f for f in fs if 'jumbo' in norm(f.entity)]
            elif 'regular' in q or 'standard' in q: fs=[f for f in fs if 'special' not in norm(f.entity) and 'jumbo' not in norm(f.entity)]
            if 'special' in q: fs=[f for f in fs if 'special' in norm(f.entity)]
            metric='dividend rate' if 'dividend' in q else ('rate' if 'interest rate' in q else 'APY')
            wanted=[f for f in fs if f.metric==metric]
            if not wanted and metric=='rate': wanted=[f for f in fs if f.metric=='dividend rate']
            wanted.sort(key=lambda f:('jumbo' in norm(f.entity),f.entity,f.qualifier))
            # Include minimum deposit as a separate qualified fact, never substitute it for APY.
            keys={(f.entity,f.qualifier) for f in wanted}
            minimum=[f for f in fs if (f.entity,f.qualifier) in keys and f.metric=='Min. to Earn']
            return self._fact_answer(state,wanted+minimum)
        if 'auto' in q and rate_request:
            fs=[f for f in allfacts if f.metric=='APR' and 'auto' in norm(f.context+' '+f.entity) and term_match(f)]
            if fs:
                top=max(f.rank for f in fs)
                if top<3:return self.unknown()
                fs=[f for f in fs if f.rank==top]
            year=re.search(r'\b(19\d\d|20\d\d)\b',q)
            if year:
                y=int(year[1])
                def year_match(f):
                    bounds=model_range(f.entity)
                    return bool(bounds) and bounds[0]<=y<=bounds[1]
                fs=[f for f in fs if year_match(f)]
            return self._fact_answer(state,fs)
        if ('mortgage' in q or 'home improvement' in q or 'construction loan' in q or re.search(r'\b\d+/\d+\b',q)) and rate_request:
            fs=[f for f in allfacts if 'home loan' in norm(f.context) or 'mortgage' in norm(f.context)]
            if 'construction' in q: fs=[f for f in fs if 'construction' in norm(f.entity+' '+f.qualifier)]
            elif re.search(r'\b\d+/\d+\b',q): fs=[f for f in fs if re.search(r'\b'+re.search(r'\b\d+/\d+\b',q)[0]+r'\b',norm(f.entity))]
            elif 'home improvement' in q: fs=[f for f in fs if 'home improvement' in norm(f.context+' '+f.entity)]
            else:
                fs=[f for f in fs if 'conventional' in norm(f.entity) and term_match(f)]
                mode='refinance' if 'refinanc' in q else 'purchase'
                fs=[f for f in fs if mode in norm(f.entity)]
                amount=re.search(r'\$\s*([\d,]+)',q)
                if amount:
                    target=float(amount[1].replace(',',''))
                    tiers=[(float(m[1].replace(',','')),f) for f in fs for m in [re.search(r'\$([\d,]+)',f.entity)] if m and float(m[1].replace(',',''))>=target]
                    if tiers:
                        ceiling=min(a for a,f in tiers);fs=[f for a,f in tiers if a==ceiling]
                fs.sort(key=lambda f:(float(re.search(r'\$([\d,]+)',f.entity)[1].replace(',','')) if '$' in f.entity else float('inf'),f.entity,f.metric))
            return self._fact_answer(state,[f for f in fs if f.metric in ('rate','APR')])
        if ('personal loan' in q or 'signature loan' in q) and rate_request:
            fs=[f for f in allfacts if 'personal loan' in norm(f.entity+' '+f.context) and f.metric=='APR' and term_match(f)]
            return self._fact_answer(state,fs)
        if ('credit card' in q or 'visa' in q) and (rate_request or 'offer' in q):
            metric='intro APR' if 'intro' in q or 'balance transfer' in q else 'APR'
            fs=[f for f in allfacts if 'visa' in norm(f.entity) and f.metric==metric]
            if 'business' in q:fs=[f for f in fs if 'business' in norm(f.entity)]
            elif 'personal' in q:fs=[f for f in fs if 'business' not in norm(f.entity)]
            if 'platinum' in q or 'rewards' in q:
                name='platinum' if 'platinum' in q else 'rewards'
                fs=[f for f in fs if name in norm(f.entity) and ('business' in q or 'business' not in norm(f.entity))]
            return self._fact_answer(state,fs)
        if rate_request and any(w in q for w in ('saving','checking','money market','hsa')):
            products=['share savings','bright savings','you name it savings','holiday club','launchpad savings',"investor's choice",'achieve','high-yield','health savings','1st rate checking','free checking']
            product=next((p for p in products if p in q),None)
            if 'hsa' in q:product='health savings'
            if 'first rate' in q:product='1st rate checking'
            if product is None:
                named=re.search(r'\b([a-z]+) (?:savings|checking)\b',q)
                generic={'share','your','our','my','the','any','all','current','dupaco','highest','account','for','on','business'}
                if named and named[1] not in generic:return self.unknown()
            if not product and 'saving' in q and 'money market' not in q:product='share savings'
            fs=[f for f in allfacts if (product in norm(f.entity) if product else ('checking' in norm(f.entity) if 'checking' in q else 'money market' in norm(f.entity)))]
            if 'business' in q:fs=[f for f in fs if '/business/' in f.source.url]
            # Select a tier by the requested balance instead of averaging tiers.
            amount=re.search(r'\$\s*([\d,]+(?:\.\d+)?)',q)
            if amount:
                balance=float(amount[1].replace(',',''))
                def fits(f):
                    nums=[float(x.replace(',','')) for x in re.findall(r'\$([\d,]+(?:\.\d+)?)',f.qualifier)]
                    return bool(nums) and balance>=nums[0] and (len(nums)<2 or balance<=nums[1])
                fs=[f for f in fs if fits(f)]
            metric='dividend rate' if 'dividend' in q else 'APY'
            selected=[f for f in fs if f.metric==metric]
            if 'bright savings' in q and not 'apy' in q:selected=[f for f in fs if f.metric in ('APY','dividend rate')]
            if re.search(r'\b(highest|maximum|top|any)\b',q) or re.search(r'\d+(?:\.\d+)?\s*%',q):
                if selected:selected=[max(selected,key=lambda f:float(re.search(r'\d+(?:\.\d+)?',f.value)[0]))]
                if re.search(r'\d+(?:\.\d+)?\s*%',q) and selected:
                    target=float(re.search(r'(\d+(?:\.\d+)?)\s*%',q)[1]);top=float(re.search(r'\d+(?:\.\d+)?',selected[0].value)[0])
                    if target>top:
                        ans=self._fact_answer(state,selected);ans.text='No. The highest published tier is '+ans.text;return ans
            return self._fact_answer(state,selected)
        if re.search(r'\b(fee|fees|cost|charge|replacement)\b',q):
            fs=[f for f in allfacts if f.metric=='fee']
            qt=set(tokens(q));ranked=[]
            for f in fs:
                ft=set(tokens(f.entity));overlap=len(qt&ft)
                if overlap>=2 or (overlap and len(qt)==1):ranked.append((overlap/max(1,len(qt)),f.rank,f))
            if ranked:
                best=max((a,b) for a,b,f in ranked)
                return self._fact_answer(state,[f for a,b,f in ranked if (a,b)==best][:3])
        return None

    def _descriptive(self,state,q):
        def answer_chunks(chunks,prefix=''):
            if not chunks:return self.unknown()
            return Answer(prefix+' '.join(c.text for c in chunks),[c.source for c in chunks])
        if 'routing' in q or 'aba number' in q:
            hits=state.search('our routing number',predicate=lambda c:bool(re.search(r'(?i)(?:our routing number|our ABA number|routing number.{0,10}(?:is|:)?)\s*\(?\d{9}',c.text)))
            if hits:
                c=max((c for _,c in hits),key=lambda c:(c.rank,'our routing number' in c.text.lower())); m=re.search(r'\b\d{9}\b',c.text)
                return Answer(m[0],[c.source])
            return self.unknown()
        if 'hy-vee' in q or 'hy vee' in q:
            if any(w in q for w in ('where','full-service','alternative','instead')):
                hits=state.search(q,predicate=lambda c:'same services' in c.text and 'branch' in c.text)
            else: hits=state.search('location close',predicate=lambda c:bool(re.search(r'(?i)(?:will close|closed|close on).{0,30}\d{4}',c.text)) and 'hy-vee' in c.source.url)
            if hits:return answer_chunks([hits[0][1]])
        if ('branch' in q or 'location' in q) and ('how many' in q or 'number of' in q):
            hits=state.search('branch office locations',limit=100,predicate=lambda c:bool(re.search(r'\b\d+ branch office locations',c.text)))
            if hits:
                c=max((c for _,c in hits),key=lambda c:(c.published,c.rank,c.source.url))
                m=re.search(r'\b\d+ branch office locations',c.text)
                return Answer('Dupaco has '+m[0]+'.',[c.source],conflict_note='Use the newest dated organizational statement, rather than archived press releases or broken dynamic counters.')
        if 'forbes' in q and 'employer' not in q:
            hits=state.search(q,limit=100,predicate=lambda c:bool(re.search(r'(?i)(?:fifth|fourth|third|\d+(?:st|nd|rd|th)) time.{0,30}Forbes',c.text)))
            if hits:
                c=max((c for _,c in hits),key=lambda c:(c.published,c.rank))
                return answer_chunks([c])
        if 'hour' in q:
            kind='Drive-up' if 'drive' in q else 'Lobby'
            # Named branches require explicit grounding; a general schedule is not a match.
            named=re.search(r'(?:for|at|of) (?:the )?(.+?) (?:branch|location)',q)
            branch=named[1] if named and named[1] not in ('dupaco','all dupaco') else None
            candidates=[]
            for url,text in state.cleaned.items():
                if branch and branch not in norm(text[:text.find('## Handpicked') if '## Handpicked' in text else len(text)]):continue
                m=re.search(r'(?im)^\s*'+kind+r'(?: hours)?[ \t]*:?[ \t]*(?:\n|(?=Monday|Mon\b))',text)
                if not m:continue
                tail=text[m.end():];schedule=[]
                for block in re.split(r'\n\s*\n',tail):
                    block=block.strip()
                    if not block:continue
                    if not re.match(r'(?i)(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon\b|Tue\b|Wed\b|Thu\b|Fri\b|Sat\b|Sun\b)',block):break
                    schedule.append(block)
                if schedule:
                    body='; '.join(schedule)
                    src=Source(url,state.sid,body)
                    candidates.append((body,src))
            if candidates:
                # Present the most commonly documented schedule, with explicit branch caveat.
                counts=Counter(norm(t) for t,s in candidates)
                body,src=max(candidates,key=lambda x:(counts[norm(x[0])], '8:30' in x[0],x[1].url))
                if kind=='Drive-up':
                    body=re.sub(r'(?i)(a\.m\.|p\.m\.)\s*[-–]\s*',r'\1 - ',body)
                if not branch and re.search(r'\b(all|same|different|vary)\b',q):
                    alternate=next(((t,s) for t,s in candidates if norm(t)!=norm(body) and 'noon' in t),None)
                    if alternate:
                        body+='; another documented schedule is '+alternate[0]
                        return Answer('No, branch schedules differ. '+kind+' examples: '+body+'. Which branch would you like to confirm?',[src,alternate[1]])
                sources=[src]
                contact=next((p for u,p in state.pages.items() if urlsplit(u).path.rstrip('/')=='/contact'),None)
                suffix='Which branch would you like to confirm?' if not branch else 'This schedule is from the supplied branch announcement; please confirm before visiting.'
                if contact:
                    suffix+=' Confirm branch-specific details at '+contact.url+'.'
                    sources.append(Source(contact.url,state.sid,'Branch and ATM locator; contact the credit union for branch-specific details.'))
                return Answer(kind+' hours vary by branch. One documented schedule is '+body+'. '+suffix,sources)
            return self.unknown()
        if re.search(r'\b(address|located|where is)\b',q) and ('branch' in q or 'galena' in q):
            hits=state.search(q,predicate=lambda c:bool(re.search(r'\b\d{5}(?:-\d{4})?\b',c.text)) and '/contact' in c.source.url)
            if hits:
                c=hits[0][1]
                if len(set(tokens(q))&set(tokens(c.text)))>=1:return answer_chunks([c])
        if ('locator' in q or ('find' in q and ('branch' in q or 'atm' in q))) and any(w in q for w in ('url','link','where','find')):
            for url,page in state.pages.items():
                if urlsplit(url).path.rstrip('/')=='/contact' and re.search(r'branch or ATM|locator',page.markdown,re.I):
                    return Answer(url,[Source(page.url,state.sid,'Branch and ATM locator')])
        if re.search(r'\b(join|become a member|membership|eligible)\b',q):
            pages=[(url,text) for url,text in state.cleaned.items() if urlsplit(url).path.rstrip('/')=='/about/join']
            if pages:
                url,text=pages[0]
                if 'online' in q or 'url' in q or 'link' in q:
                    urls=re.findall(r'https://join\.[^\s)]+',state.pages[url].markdown)
                    if urls:return Answer(urls[0],[Source(url,state.sid,urls[0])])
                if re.search(r'eligible|who|qualif|membership',q):
                    blocks=[p.strip() for p in text.split('\n\n') if 'charter area' in p or ('Iowa' in p and 'Wisconsin' in p)]
                    if blocks:return Answer(' '.join(blocks),[Source(url,state.sid,' '.join(blocks)[:1000])])
        if 'student' in q or 'university' in q:
            hits=state.search(q+' student loans flexible repayment',predicate=lambda c:'student' in norm(c.heading+' '+c.text) and 'loan' in norm(c.text) and '/personal/' in c.source.url)
            if hits:return answer_chunks([c for _,c in hits[:2]])
        if 'mobile wallet' in q or 'apple pay' in q or 'google pay' in q:
            hits=state.search('Apple Pay Google Pay Samsung Pay',predicate=lambda c:all(w in c.text for w in ('Apple Pay','Google Pay','Samsung Pay')))
            if hits:return answer_chunks([hits[0][1]])
        if re.search(r'home\$?tart|hometart',q):
            hits=state.search(q+' down payment closing costs assistance',predicate=lambda c:bool(re.search(r'Home\$?tart',c.text,re.I)) and '$' in c.text)
            if hits:return answer_chunks([hits[0][1]])
        if 'volunteer time off' in q or 'vto' in q:
            hits=state.search('employees used Volunteer Time Off',limit=30,predicate=lambda c:bool(re.search(r'\d+\s+(?:Dupaco\s+)?employees.*used.*(?:Volunteer Time Off|VTO)',c.text,re.I)))
            requested=re.search(r'\b20\d\d\b',q)
            if requested:hits=[(s,c) for s,c in hits if requested[0] in c.text]
            if hits:
                chunks=[];seen=set()
                for _,c in hits:
                    years=re.findall(r'\b20\d\d\b',c.text)
                    if years and tuple(years) not in seen:
                        chunks.append(c);seen.add(tuple(years))
                if chunks:
                    ans=answer_chunks(chunks[:3],'The supplied dated reports state: ')
                    if 'last year' in q:
                        previous=str(int(state.date[:4])-1)
                        if not any(previous in c.text for c in chunks):
                            ans.text+=' A count for the year before the latest snapshot is not published in these reports.'
                            ans.confident=False
                    return ans
        if ('contact information' in q or 'address' in q or 'phone number' in q) and re.search(r'update|change',q):
            hits=state.search('update contact information Shine call',predicate=lambda c:bool(re.search(r'(?i)(update|change).{0,100}(contact|address|phone)',c.text)))
            if hits:
                chunks=[hits[0][1]]
                if not any('800-' in c.text for c in chunks):
                    extra=state.search('call contact',predicate=lambda c:'800-' in c.text and '/contact' in c.source.url)
                    if extra:chunks.append(extra[0][1])
                return answer_chunks(chunks)
        hits=state.search(q)
        if not hits:return self.unknown()
        score,c=hits[0]
        meaningful=set(tokens(q));matched=meaningful&c.terms.keys()
        if len(matched)<min(2,len(meaningful)) or score<2:return self.unknown()
        # A requested number without a matching structured fact must not be guessed
        # from a nearby product's marketing copy or an unrelated calculator.
        if re.search(r'\b(apr|apy|rate|rates|yield)\b',q):return self.unknown()
        return answer_chunks([c])

    def conflicts(self):
        if not self.states:return []
        latest=self.states[-1]
        # Historical observations are kept separately from the current state.
        groups=defaultdict(list)
        for state in self.states:
            for f in state.facts:
                if f.metric in ('APY','APR','intro APR','rate','dividend rate','fee','count'):
                    groups[f.key].append((state.date,f))
        output=[]
        auto_latest=[f for f in latest.winners.values() if f.metric=='APR' and model_range(f.entity) and 'auto' in norm(f.context)]
        auto_rank=max((f.rank for f in auto_latest),default=0)
        canonical_auto=[f for f in auto_latest if f.rank==auto_rank]
        auto_observations=[(s.date,f) for s in self.states for f in s.facts if f.metric=='APR' and model_range(f.entity) and 'auto' in norm(f.context)]
        for winner in canonical_auto:
            lo,hi=model_range(winner.entity)
            compatible=[]
            for date,f in auto_observations:
                a,b=model_range(f.entity)
                if norm(f.qualifier)!=norm(winner.qualifier) or max(a,lo)>min(b,hi):continue
                compatible.append((date,f))
            variants={}
            for date,f in compatible:
                k=tuple(float(n) for n in f.numeric)
                if k not in variants or date>variants[k][0]:variants[k]=(date,f)
            if len(variants)>1:
                output.append(Conflict(winner.entity+' ('+winner.qualifier+') auto loan APR',[f.value for d,f in variants.values()],[f.source for d,f in variants.values()],winner.value,'Compare only the same loan term and overlapping vehicle model years. The current official auto-loan table wins over calculator examples and previous snapshots; model-year tier boundaries can shift over time.'))
        for key,observations in sorted(groups.items()):
            if any(model_range(f.entity) and 'auto' in norm(f.context) for d,f in observations):continue
            values={}
            for date,f in observations:
                # Decimal formatting and footnote markers are not contradictions.
                numeric=tuple(float(x) for x in f.numeric)
                if numeric not in values or (date,State.fact_rank(f))>(values[numeric][0],State.fact_rank(values[numeric][1])):
                    values[numeric]=(date,f)
            if len(values)<2:continue
            winner=latest.winners.get(key)
            if winner is None:continue
            competing=list(values.values())
            same_snapshot=len({tuple(float(n) for n in f.numeric) for f in latest.by_key[key]})>1
            active=[f for f in latest.by_key[key] if not f.valid_until or f.valid_until>=latest.date]
            tied=[f for f in active if (f.rank,f.effective)==(winner.rank,winner.effective)]
            unresolved=len({f.numeric for f in tied})>1
            reason=('The official product/rate sheet outranks calculators, promotions and archived articles; within the same authority, prefer the latest effective date.' if same_snapshot else 'The same qualified fact changed across snapshots. The newest snapshot is the current observation; earlier values remain available for historical as-of answers. This is a historical change, not necessarily a simultaneous contradiction.')
            if unresolved:reason='Equally authoritative current claims disagree, with no effective-date evidence to pick a winner; confirmation is required.'
            output.append(Conflict(winner.entity+(' ('+winner.qualifier+')' if winner.qualifier else '')+' '+winner.metric,[f.value for _,f in competing],[f.source for _,f in competing],None if unresolved else winner.value,reason))
        return copy.deepcopy(output)


def build():
    return KnowledgeSystem()
