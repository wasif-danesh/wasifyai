# IR0: Reference and Inpaint on FLUX.2 klein 4B (run 2026-10-21)

What `docs/image-inpaint-reference-plan.md` asked for before any product code: build the graphs by hand in ComfyUI on this Mac (M5 Pro,
64 GB; ComfyUI 0.40.0, the version the app pins; the shared klein 4B files) and look at the pictures. Pictures: `docs/spikes/image-ir0/`
(left to right: the inputs, then the results). Then the product was built from the winners (`products/wasifyai-image/workflows/`).

## Reference (two pictures and a prompt)

The Edit graph with a second `ReferenceLatent` pair: each picture is scaled, encoded and fed to the positive and negative
conditioning one after the other; the size is the person's choice.

| Test | Result | Time |
|---|---|---|
| cat + chair (`sheet-ref1.jpg`) | the cat's face and markings and the chair's shape, wood and green seat all kept, in a sunlit room | 60 s (cold) |
| mascot + building, wide 1344x768 (`sheet-ref2.jpg`) | both kept, golden-hour light | 47 s |
| sneaker + plant (`sheet-ref3.jpg`) | the sneaker's design and the pot and plant kept | 72 s |
| robot toy + toy car, 1216x832 (`sheet-ref4.jpg`) | the robot sits in the car; both recognisable | 109 s |

**Speed.** The time grows with the number of pictures, because each adds image tokens to the model's attention: about 8 s per step with no
reference, 13 s with one, 22 s with two (a busy Mac: the browser pane and other sessions were running). At **half a megapixel per
reference** the same test takes **about 70 s** (a quarter: 46 s) against 100 to 120 s at a full megapixel, and both subjects stay
recognisable (`sheet-mp.jpg`, left to right: 1 MP, 0.5 MP, 0.25 MP). The product uses 0.5 MP. Memory: ComfyUI holds the 7.4 GB model.

## Inpaint (a picture, a painted area, a prompt)

Three ways, each pasting the result back through the (grown, softened) mask with `ImageCompositeMasked`:

- **A** a latent noise mask (`SetLatentNoiseMask`) on the encoded picture, no reference;
- **B** the **Edit graph on a copy of the picture with the painted area filled white**, told "fill the white area with ...";
- **C** A with the picture as a reference.

| Case | A | B | C |
|---|---|---|---|
| a red velvet cushion on a chair seat (`sheet-inp-seat.jpg`; order: source, marked, A, B, C) | partly covered, green left | **a clear red velvet cushion** | partly covered, green left |
| a white coffee cup beside a plant pot (`sheet-inp-coffee.jpg`) | only a faint ghost of a handle | **a real cup with steam** | a ghost of a handle |
| the cat replaced by a dog, same pose (`sheet-inp-dog.jpg`, B only) | | **a dog in the same pose and light** | |

**B wins on every case** and is what the product uses. Its weakness is a faint lighter halo where the join is (the model redraws the whole
picture and its tones differ a little from the source); a wider softening (grow 12, blur 14) made it softer (`sheet-inp-coffeewide.jpg`) and
is the product's setting. Time 28 to 60 s.

**The guarantee holds.** Two inpaint runs on the same picture and mask with different prompts and seeds (the product's own workflow and
fill code, a 1500x1000 picture and a mask drawn at another size) agree on **all 916,567 pixels outside the grown mask, with a maximum
difference of 0**. The picture is worked on at about one megapixel (1248x832 for a 3:2 picture), so a larger picture comes back at that
size.

**Limits seen.** A small area is sometimes ignored: asking for a frog in a small painted area left the picture unchanged. A tight
rectangle can cut the new object at its edge (the cup in the app test is clipped on its left). Colour matching at the join and a
crop-around-the-mask pass for small areas are possible follow-ups, not built.

## In the real app

Both were run through the actual screens on the dev engine with the spike ComfyUI as an external image engine (`DESKTOP_IMAGE_ENGINE=external`):
Reference with the cat and the chair (1024x1024, saved as a `reference` image with its recipe), and Inpaint with a rectangle painted
with the mouse on the real canvas and a coffee-cup prompt (saved as an `inpaint` image, size `null`); after each run no upload was left on
disk. The Tauri window itself was not used (the browser pane stands in for it), and the runs took 60 to 137 s on a busy Mac.

## Not tried

Qwen-Image 2.1 (on this Mac, not in `models.yaml`, licence unread): the klein results were good enough that it was not needed. 16 and
32 GB Macs. More than two reference pictures (the owner chose two).
