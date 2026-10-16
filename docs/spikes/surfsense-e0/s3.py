import json, re, subprocess, sys, time, urllib.request
import nbcore as nb
from collections import defaultdict
qs=json.load(open("questions.json"))
HEADER=("These are excerpts from the user's knowledge base, selected for this query.\nA document is a full source; each <document> below is in excerpt view, so you are seeing only the chunks that matched this query, not the whole source. Cite a chunk with its [n].")
TAGS=re.compile(r"</?(?:source|context|document|retrieved_context)\b[^>]*>",re.I)
def build(hits):
    grouped=defaultdict(list); order=[]
    for i,(cid,_,_) in enumerate(hits,1):
        d=nb.doc(cid)
        if d not in grouped: order.append(d)
        grouped[d].append((i,cid))
    out=[]
    for d in order:
        lines=[f'<document title="{d}" view="excerpt">']
        for i,cid in grouped[d]:
            body=TAGS.sub("",nb.text(cid)).strip().replace("\n","\n      ")
            lines.append(f"  [{i}] {body}")
        lines.append("</document>"); out.append("\n".join(lines))
    return "<retrieved_context>\n"+HEADER+"\n"+"\n".join(out)+"\n</retrieved_context>"
def ask(system,user):
    body=json.dumps({"messages":[{"role":"system","content":system},{"role":"user","content":user}],"temperature":0.2,"max_tokens":500,"chat_template_kwargs":{"enable_thinking":False}}).encode()
    t=time.time()
    r=json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8089/v1/chat/completions",body,{"Content-Type":"application/json"}),timeout=300))
    return r["choices"][0]["message"]["content"], time.time()-t, r["usage"]
REFUSE=re.compile(r"don't|do not|doesn't|does not|not cover|not provide|no information|not mention|not specif|isn't|not in the|cannot|can't|unable|not available|no mention|not include",re.I)
summary={}
for tier in ("compact","capable"):
    system=open(f"{tier}.md").read()
    ok=cited=refused=bad_unans=0; times=[]; log=[]
    for x in qs:
        hits=nb.rank(x["q"],"hybrid",top=5)
        user=build(hits)+"\n\nQuestion: "+x["q"]
        ans,dt,u=ask(system,user); times.append(dt)
        labels=[int(n) for n in re.findall(r"\[(\d+)\]",ans)]
        if x["expect"]:
            right=x["expect"].lower() in ans.lower()
            sup=any(1<=n<=len(hits) and x["expect"].lower() in nb.text(hits[n-1][0]).lower() for n in labels)
            ok+=right; cited+=(right and sup)
            log.append(dict(q=x["q"],right=right,supported_cite=sup,ans=ans[:300]))
        else:
            ref=bool(REFUSE.search(ans)); refused+=ref
            fab=any(1<=n<=len(hits) for n in labels)
            bad_unans+=fab
            log.append(dict(q=x["q"],refused=ref,cited_anyway=fab,ans=ans[:300]))
    n_a=sum(1 for x in qs if x["expect"]); n_u=len(qs)-n_a
    summary[tier]=dict(answerable=n_a,correct=ok,correct_with_supported_citation=cited,unanswerable=n_u,refused=refused,cited_an_unanswerable=bad_unans,median_s=round(sorted(times)[len(times)//2],1),max_s=round(max(times),1))
    json.dump(log,open(f"s3_{tier}.json","w"),indent=1,ensure_ascii=False)
    print(tier,json.dumps(summary[tier]),flush=True)
json.dump(summary,open("s3_summary.json","w"),indent=1)
print(subprocess.run("ps -o rss=,comm= -p $(cat llama.pid)",shell=True,capture_output=True,text=True).stdout)
