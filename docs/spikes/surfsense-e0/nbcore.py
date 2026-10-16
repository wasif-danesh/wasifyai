import json, os, pathlib, sqlite3, sys, time, resource
os.environ["NB_MODELS_DIR"]=str(pathlib.Path("models").resolve())
import numpy as np, sqlite_vec
from lifted import encoder, chunking
from lifted.bundled import BGE
from lifted.tokenizer import TOKENIZER, terms
W=BGE.semantic_weight
rss=lambda: round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1048576)
db=sqlite3.connect(":memory:"); db.enable_load_extension(True); sqlite_vec.load(db); db.enable_load_extension(False)
db.executescript(f"""
CREATE TABLE documents(id INTEGER PRIMARY KEY, title TEXT);
CREATE TABLE chunks(id INTEGER PRIMARY KEY, document_id INT, position INT, content TEXT, start_line INT, end_line INT);
CREATE VIRTUAL TABLE chunks_fts USING fts5(content, content='chunks', content_rowid='id', tokenize="{TOKENIZER}");
CREATE VIRTUAL TABLE chunk_vectors USING vec0(embedding float[384]);
""")
docs={}
t0=time.time(); nchunks=0; embed_s=0
files=sorted(list(pathlib.Path("md").glob("*.md")))+[pathlib.Path("corpus/synth/notes.md")]
for f in files:
    name=f.name[:-3] if f.name.endswith(".pdf.md") or f.name.endswith(".docx.md") or f.name.endswith(".pptx.md") or f.name.endswith(".xlsx.md") or f.name.endswith(".html.md") or f.name.endswith(".csv.md") else f.name
    cur=db.execute("INSERT INTO documents(title) VALUES(?)",(name,)); did=cur.lastrowid; docs[did]=name
    ps=chunking.chunk(f.read_text())
    t=time.time(); vecs=encoder.embed(BGE,[p.text for p in ps],encoder.Purpose.DOCUMENT); embed_s+=time.time()-t
    for i,(p,v) in enumerate(zip(ps,vecs)):
        cid=db.execute("INSERT INTO chunks(document_id,position,content,start_line,end_line) VALUES(?,?,?,?,?)",(did,i,p.text,p.start_line,p.end_line)).lastrowid
        db.execute("INSERT INTO chunks_fts(rowid,content) VALUES(?,?)",(cid,p.text))
        db.execute("INSERT INTO chunk_vectors(rowid,embedding) VALUES(?,?)",(cid,sqlite_vec.serialize_float32(v)))
    nchunks+=len(ps)
print(f"ingested {len(docs)} docs, {nchunks} chunks in {time.time()-t0:.1f}s (embedding {embed_s:.1f}s), peak {rss()} MB",flush=True)
K=20
def matching(match,within=None):
    sql="SELECT c.id FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.rowid WHERE chunks_fts MATCH ?"
    p=[match]
    if within is not None: sql+=" AND c.id IN (%s)"%",".join("?"*len(within)); p+=list(within)
    return [r[0] for r in db.execute(sql+" ORDER BY bm25(chunks_fts) LIMIT %d"%K,p)]
def lexical(q):
    ts=terms(q)
    if not ts: return {}
    cand=matching(" OR ".join(f'"{t}"' for t in ts))
    cov=dict.fromkeys(cand,0)
    for t in ts:
        for c in matching(f'"{t}"',cand): cov[c]+=1
    return {c:n/len(ts) for c,n in cov.items()}
def cos_all(vec):
    return {r[0]:1-r[1] for r in db.execute("SELECT rowid, vec_distance_cosine(embedding,?) FROM chunk_vectors",(vec,))}
def vector_leg(vec):
    return [r[0] for r in db.execute("SELECT rowid FROM chunk_vectors WHERE embedding MATCH ? AND k=?",(vec,K))]
def rank(q,mode,top=10):
    vec=sqlite_vec.serialize_float32(encoder.embed(BGE,[q],encoder.Purpose.QUERY)[0])
    kw=lexical(q); vl=vector_leg(vec)
    cand=set(kw)|set(vl) if mode=="hybrid" else (set(kw) if mode=="lexical" else set(vl))
    cs=cos_all(vec) if cand else {}
    def score(c):
        s=max(0,cs[c])
        if mode=="dense": return s
        if mode=="lexical": return kw.get(c,0)
        return W*s+(1-W)*kw.get(c,0)
    order=sorted(cand,key=lambda c:(-score(c),-cs[c]))
    return [(c,score(c),cs[c]) for c in order[:top]]
def text(c): return db.execute("SELECT content FROM chunks WHERE id=?",(c,)).fetchone()[0]
def doc(c): return docs[db.execute("SELECT document_id FROM chunks WHERE id=?",(c,)).fetchone()[0]]
