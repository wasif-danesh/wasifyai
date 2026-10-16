import os,pathlib,random,sqlite3,time
os.environ["NB_MODELS_DIR"]=str(pathlib.Path("models").resolve())
import numpy as np, sqlite_vec
from lifted import encoder
from lifted.bundled import BGE
from lifted.tokenizer import TOKENIZER
random.seed(1); np.random.seed(1)
words=" ".join(p.read_text() for p in pathlib.Path("md").glob("*.md")).split()
db=sqlite3.connect(":memory:"); db.enable_load_extension(True); sqlite_vec.load(db)
db.executescript(f"""CREATE TABLE chunks(id INTEGER PRIMARY KEY, content TEXT);
CREATE VIRTUAL TABLE fts USING fts5(content, content='chunks', content_rowid='id', tokenize="{TOKENIZER}");
CREATE VIRTUAL TABLE v USING vec0(embedding float[384]);""")
n=0
def grow(to):
    global n
    rows=[]
    while n<to:
        n+=1; txt=" ".join(random.sample(words,150))
        v=np.random.randn(384).astype(np.float32); v/=np.linalg.norm(v)
        db.execute("INSERT INTO chunks(id,content) VALUES(?,?)",(n,txt)); db.execute("INSERT INTO fts(rowid,content) VALUES(?,?)",(n,txt))
        db.execute("INSERT INTO v(rowid,embedding) VALUES(?,?)",(n,sqlite_vec.serialize_float32(v.tolist())))
for size in (10_000,100_000):
    t=time.time(); grow(size); build=time.time()-t
    q=sqlite_vec.serialize_float32(encoder.embed(BGE,["What is the minimum passing score for the exam?"],encoder.Purpose.QUERY)[0])
    ts=[]
    for _ in range(5):
        t=time.time()
        db.execute("SELECT rowid FROM v WHERE embedding MATCH ? AND k=20",(q,)).fetchall()
        db.execute('SELECT rowid FROM fts WHERE fts MATCH \'"minimum" OR "passing" OR "score" OR "exam"\' ORDER BY bm25(fts) LIMIT 20').fetchall()
        ts.append(time.time()-t)
    print(f"{size} chunks: build {build:.0f}s; both legs median {sorted(ts)[2]*1000:.0f} ms",flush=True)
