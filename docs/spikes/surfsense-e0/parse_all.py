import json, os, pathlib, resource, sys, time
t0=time.time()
models=pathlib.Path("models/docling").resolve()
os.environ["HF_HOME"]=str(pathlib.Path("models/hf").resolve()); os.environ["HF_HUB_OFFLINE"]="1"
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption
import psutil
o=PdfPipelineOptions(); o.do_ocr=True; o.do_table_structure=True
o.accelerator_options=AcceleratorOptions(num_threads=min(8,psutil.cpu_count(logical=False) or 4))
o.artifacts_path=models; o.ocr_options=RapidOcrOptions(use_cls=False)
conv=DocumentConverter(allowed_formats=[InputFormat.PDF,InputFormat.DOCX,InputFormat.PPTX,InputFormat.XLSX,InputFormat.HTML,InputFormat.CSV,InputFormat.MD,InputFormat.IMAGE],
  format_options={InputFormat.PDF:PdfFormatOption(pipeline_options=o),InputFormat.IMAGE:ImageFormatOption(pipeline_options=o)})
rss=lambda: round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1048576)
print("import+build s",round(time.time()-t0,1),"peak MB",rss(),flush=True)
files=sorted(pathlib.Path("corpus").rglob("*.*"))
out=pathlib.Path("md"); out.mkdir(exist_ok=True)
rows=[]
import pypdfium2
for f in files:
    if f.suffix in(".md",): continue
    pages=None
    if f.suffix==".pdf": pages=len(pypdfium2.PdfDocument(str(f)))
    t=time.time(); err=None
    try:
        md=conv.convert(f).document.export_to_markdown()
        (out/(f.name+".md")).write_text(md)
    except Exception as e:
        md=""; err=repr(e)[:200]
    dt=time.time()-t
    r=dict(file=f.name,kb=round(f.stat().st_size/1024),pages=pages,seconds=round(dt,1),chars=len(md),per_page=round(dt/pages,2) if pages else None,peak_mb=rss(),err=err)
    rows.append(r); print(json.dumps(r),flush=True)
json.dump(rows,open("parse_results.json","w"),indent=1)
print("total s",round(time.time()-t0,1))
