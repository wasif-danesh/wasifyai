# ADR-0106: Capturing a website's screens: a tool of the Wasify engine, with sign-in done by the person

- **Status:** Proposed (2026-11-14). Nothing is built. The spike at the end comes first.
- **Date:** 2026-11-14
- **Changed the same day, by the owner:** "Permissions should have an option to accept all for a project or similar
  so users don't need to allow 20 different permissions." See "Fewer cards".
- **Asked for by the owner, 2026-11-14:** "I need a way in the coding agent to record a website's screens from the
  instructions or context in the chat. It should be able to take the screenshots using headless chrome or similar and
  then use it in motion graphics, word, power point, pdf etc. files." And: "It should work for both public and private
  pages. If it needs sign in it should ask user to do so."
- **Keeps:** ADR-0102 (the coding engine in a sandbox with no internet, the key outside), ADR-0068 (every feature is
  an action), ADR-0069 (the MCP server and its approvals), ADR-0070 (the address rule and the taint rule), ADR-0077
  (a browser that runs outside code is locked down), ADR-0041 (every new kind of creation can be searched), rule 6
  (slow work is a job), rule 7 (tenancy), rule 9 (usage), rule 10 (files through storage), rule 13 (secrets).
- **Touches:** choice 15 of `docs/spikes/coding-mockups.md` ("The Browser tab is the person's. The agent does not
  browse"). That choice can stay: under this decision the agent still does not browse. It asks the engine for a
  capture.
- **Also touches:** choice 12 of the same notes ("No 'don't ask again' on the approval card", recommended for v1).
  The owner's rule of 2026-11-14 answers that choice the other way: a card can be allowed for the project.
- **Goes with:** ADR-0104 (Wasify's own skills, for Word, PowerPoint and PDF).
- **Number:** 0106 was free on every branch on 2026-11-14. If another branch takes it first, this one moves up.

## Context

The owner wants to say in a coding session "take pictures of the pricing page and the dashboard of this site and
put them in a slide deck", and get the files.

What is in the way today:

- **The coding sandbox has no internet** (ADR-0102, decision 3). The planned proxy lets package hosts through, not
  websites. `sandbox-exec` cannot filter by host name.
- **A headless browser cannot show a sign-in page to a person.** A private page needs the person, a visible window
  and somewhere to keep the session afterwards.
- **A signed-in browser is a much bigger risk than a public one.** A click can change or delete something. What is
  on the page is personal. A web page can hold text written to steer a model.
- **Motion graphics has no tool that takes a file.** Its tools use only what Wasify AI makes (`motion.make_file`).
  "Media from computer" is a button on the screen.
- **The pinned skills catalogue has nothing for Word, PowerPoint or PDF** (only `pdflatex`).

What is already there:

- A pinned Chrome headless shell (152.0.7977.30, 97.5 MB download) is installed with Motion graphics, with a launcher
  that removes weak flags and a filter proxy on loopback (`video_builder_sandbox.py`).
- The address rule: a name that resolves to a private or link-local address is refused unless the person typed that
  address (`mcp_client/servers.py`, `check_url` and `resolve_host`).
- The chat assistant's `web.read` and `web.search`, with the "leaves this computer" flag and its approval.
- The taint rule: after the model has read something from outside, the next action asks first and says why.
- The app's own FFmpeg, and the Library with one search.

Measured for this ADR: the full Chrome for Testing at the same version is a **187 MB** download for Apple silicon
(the size the public server reports; not downloaded).

## Decision

### The tool

1. **One action, `web.capture`, run by the Wasify engine outside the coding sandbox.** It is offered to the chat
   assistant and to other apps through the MCP server, so a coding session reaches it through its short set of tools
   (ADR-0102, decision 8). The sandbox stays closed to the internet.
2. **A capture is a script, not a live browser.** The request says everything at once:
   - the address;
   - the size: desktop (1440 by 900), phone (390 by 844) or given numbers;
   - what to take: a picture of the view, a picture of the whole page, or a recording of up to 60 seconds;
   - steps in order: go to an address on the same site, wait, scroll, hover, click, type;
   - a name for the files.

   The run does those steps and nothing else. The agent cannot add a step after the person has said yes. To go
   further it asks for another capture.
3. **It asks first for a new site.** The card names the site, what will be taken and each step in plain words. The
   flag is "leaves this computer". The card has **Allow once** and **Allow for this project**. How a project stops
   asking altogether is in "Fewer cards".
4. **A capture is a job** (rule 6): it can be stopped, stopping reaches the browser's whole process group, and it
   shows in Running now. At most 20 pictures or one recording per run. Each run writes a usage event.
5. **What it makes.** PNG pictures and, for a recording, an MP4 (H.264) joined by the app's own FFmpeg from the
   browser's frames. The files are a new kind in the Library, "Screen captures", found by the one search
   (ADR-0041). When a coding session asked, a copy also lands in its workspace under `captures/`.

### The browser

6. **The browser runs locked down, as in ADR-0077:** a profile of Wasify's own, no extensions, no downloads, no
   permission prompts, a time limit, a memory watchdog and an empty environment.
7. **It reaches the network only through a proxy in the Wasify engine.**
   - The page and every step stay on the approved site. A step that leaves it ends the run and says so.
   - The page's own pictures, fonts and scripts may come from other public hosts.
   - This computer and private addresses are closed by the address rule of ADR-0070, checked on the resolved
     address. A site on the person's own network is allowed only when the person named that address and the card
     says "on your network".
8. **Which browser** depends on the sign-in choice below. For public pages the headless shell the app already ships
   is enough, with no new download.

### Private pages: the person signs in

9. **The agent never signs in.** It never types a password, a code or a card number. A step that types into a
   password field is refused. Wasify AI never stores a password.
10. **How the need is noticed.** A capture ends as `needs_sign_in` when the page answers 401 or 403, when the run
    lands on another address that has a password field, or when the model says the picture is a sign-in page. The
    person can also sign in ahead of time ("sign me in to this site").
11. **The person is asked in the session.** A card says "*site* asks you to sign in" with **Open the sign-in
    window** and **Skip**. Skip returns a plain "not signed in" to the agent.
12. **The sign-in window is the person's.** It is a visible window at that site. While it is open the agent is
    paused: it takes no picture, runs no step and sees nothing. Codes, passkeys and "I am not a robot" checks are
    the person's to do. The window has **Done** and **Cancel**.
13. **After Done the capture runs again, once.** If the page still asks for sign-in the run stops and says so.
14. **One browser profile per site and per person**, in the app's data folder, outside every workspace and outside
    the coding sandbox. The session is kept there by the browser. The profiles are listed in Settings under
    Privacy as "Signed-in sites", each with **Forget**. When a session has run out, the person is asked again.
15. **How the sign-in window is made is open until the spike.** Three ways:

    | Way | What it costs | What may break |
    |---|---|---|
    | **A. The full Chrome for Testing as a visible window**, with the same profile the capture then uses (recommended) | A new optional part of 187 MB | Least: one browser for both steps |
    | **B. A window of Wasify's own** (the Browser tab), and its session copied to the capture browser | No download | Sites that keep the session outside cookies or tie it to the browser |
    | **C. The capture browser shown as a live picture inside Wasify**, with clicks and keys passed on | No download | Passkeys; the password passes through our code; big providers may refuse a browser they see as driven |

### A signed-in site is treated more strictly

16. **It asks once for each site in a project,** when the person chooses **Allow for this project** on its card.
    The project's "Work on its own" mode does not cover a signed-in site by itself: each one is allowed by name.
17. **The card lists every click and every typed text in words.** The run does exactly those. After the site is
    allowed for the project, the same list is shown as a quiet line in the session, not as a card.
18. **What the model sees.** The pictures are always saved. Whether the model also looks at them is a choice on the
    card. When the model is in the cloud and the site is signed in, the default is no: the agent gets the file
    names, the sizes and the page titles only.
19. **Text on a captured page is outside content.** The taint rule of ADR-0070 applies to whatever the agent does
    next.
20. **Signed-in captures are marked private** in the Library and are never used by another product without the
    person choosing them.

### Fewer cards

The owner's rule: an agent that asks twenty times is not usable. The coding sandbox is what makes this safe: with
every card switched off, the agent still cannot write outside the project, read the rest of the home folder or reach
the internet by itself.

21. **Allow for this project** is on every card a coding session shows, for captures and for Wasify's products as
    tools (a picture, music, speech, a clip). It covers that kind of request in that project from then on.
22. **The project's mode decides the rest.** The mockups already draw three modes for a project: Plan, Ask me,
    Work on its own. In "Work on its own" the agent does not ask for captures of public sites, for Wasify's
    products as tools, for commands or for edits. One choice replaces the twenty cards.
23. **What still asks, in every mode:**
    - deleting something of the person's outside the project, which is the floor of ADR-0068;
    - the sign-in itself, because only the person can do it;
    - the first capture of each signed-in site (decision 16);
    - a cost limit that has been reached (ADR-0102).
24. **The person can see and take back what was allowed.** The project's settings list "What this project may do":
    its mode, each allowed kind of request and each allowed site, each with **Remove**.
25. **An allowance belongs to one project and one person.** It is never carried to another project, and a new
    project starts in "Ask me".
26. **Allowed work is still shown.** Each capture and each tool call is a quiet line in the session with what it did,
    and stays in the activity list.

### Using the captures

27. **Motion graphics gets one new action, `motion.add_file`:** a file from the Library or from a session's
    workspace becomes an asset of a project, with the checks "Media from computer" already does (type, size up to
    100 MB). A scene then uses it like any other picture or background.
28. **Word, PowerPoint and PDF are skills of Wasify's own** in the Extensions catalogue (ADR-0104, stage X2). Word
    and PowerPoint are written by code in the workspace (`python-docx`, `python-pptx`, installed through the
    package proxy of stage C3). A PDF is printed from a page by the capture browser, so it needs nothing new.
29. **No switch.** The tool is offered when its parts are installed.

### Where

30. **Desktop, Mac first**, with the coding engine. On the web, public captures can run on an engine worker
    (ADR-0087) later. Signed-in captures on the web are not decided here: a browser on a server would hold a
    person's sign-ins.

## Limits the person will meet

- A site may show a cookie banner in the picture, or refuse a browser it sees as automated.
- The sign-in window starts clean. The person's own password manager and saved sign-ins are not in it.
- Some sites tie a session to the device and will ask again each time.
- A recording has no sound.
- The agent cannot hear or judge a recording. With pictures hidden from the model, it cannot check them either.

## The spike (WC0), before anything is built

Outside the repository, with the engine's real parts. It needs the owner's yes for one 187 MB download and for a
test account on one real provider.

| # | Question | Go when |
|---|---|---|
| 1 | A public page through the proxy: a view, a whole page, a 10 second recording | The files are right, with time and memory written down |
| 2 | A page that reaches for this computer and a private address | Both are refused and listed |
| 3 | Sign-in by ways A, B and C on a cookie site of our own, a site of our own that keeps its session in storage, and one real provider | For each way: does the capture see the signed-in page, and still after the app starts again |
| 4 | Can the headless shell use a profile the full browser signed in to | Yes or no. If yes, captures keep using the shell |
| 5 | Where the session lies on disk and what a copy of the folder gives another program | Written down, with the keychain item it depends on |
| 6 | Noticing a sign-in page, on 20 sites | The count of wrong yes and wrong no |
| 7 | A capture into a Motion graphics scene, a Word file, a PowerPoint file and a PDF | Each opens in its own app and shows the picture |
| 8 | The tool called from a coding session inside the sandbox | The file lands in the workspace and the card shows in the session |
| 9 | A local model, the engine and the browser at once | Memory written down; no job is lost |

## For the owner to decide

1. **The sign-in window:** way A with its 187 MB part (recommended), or B, or C. Best decided after spike 3.
2. **May a cloud model look at pictures of signed-in pages?** Recommended: asked on the card, off by default.
3. **How long a sign-in is kept:** until Forget (recommended), or only until the app is closed.
4. **Typing on a signed-in site:** allowed when the card shows the text (recommended), or never.
5. **When:** with stage C4, which already brings the products as tools (recommended), or a stage of its own after.
6. **The spike:** may it download the 187 MB browser and use a test account of yours on one provider?
7. **Sites on your own network:** allowed with a card that says so (recommended), or not at all.
8. **Does "Work on its own" also cover signed-in sites without naming each one?** Recommended: no, one card per
   site and project. A page on a signed-in site can hold text written to steer the agent, and a click there can
   change something of yours.
9. **Fewer cards for the whole coding agent.** Decisions 21 to 26 are written for captures and for Wasify's tools.
   The same rule for commands and edits belongs with the modes in `docs/spikes/coding-mockups.md` and ADR-0102.
   Recommended: one rule for all of it, decided there.

## Consequences

- The coding sandbox does not change. The internet stays outside it.
- The engine gains a second locked-down browser job beside the Motion graphics render, and a second proxy rule.
- The app holds signed-in browser profiles for the first time. They are personal data, they need the Privacy entry
  and Forget from the first stage, and they are never part of a backup or a workspace.
- The chat assistant gains the same tool at no extra cost.
- A project keeps a list of what it may do. That is new state per project and person, with its own screen.
- With "Work on its own", the sandbox, the proxy and the cost limit are the only guards on a public capture. The
  hostile tests must cover that mode.
- The short set of tools for a coding session now has to hold `web.capture` and `motion.add_file`.
- Two new workspace packages are named for the document skills. They are installed per workspace, not into the app.
