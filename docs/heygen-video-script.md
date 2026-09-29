# Video Script: "Turn a Google Sheet into AI Avatar Videos with n8n + HeyGen"

**Length:** about 8–12 min
Each scene gives **what to show** and **what to say**. The quotes are a starting point; say them in your own words.

**The workflow (left to right):**
Schedule Trigger (8AM Daily) → Read Rows — Ready for Video → Submit to HeyGen API → Extract Video ID → Wait 60 Seconds → Poll HeyGen Status → Check Status + Build State → Is Video Done?
- **true** → Download Video from HeyGen → Upload Video to Google Drive → Update Sheet — Ready to Post
- **false** → loops back to Wait 60 Seconds

---

### Scene 1 – Hook (0:00–0:40)
**Show:** the Google Sheet with a row marked *Ready for Video*. Cut to the finished video playing in Google Drive, then back to the sheet, where the row now says *Ready to Post*.
**Say:**
> "Every morning at 8AM, this workflow takes the scripts I've written in a Google Sheet, turns them into AI avatar videos with HeyGen, saves them to Google Drive, and marks them ready to post. I don't click anything. I write the script, and the video is waiting for me later."

### Scene 2 – The problem it solves (0:40–1:30)
**Show:** yourself (or a slide): *Write script → open HeyGen → paste → wait → download → upload → update tracker.*
**Say:**
- "If you make short-form content, you know the boring part isn't writing. It's the copying, pasting, waiting and downloading."
- "Do that for five videos a day and you lose an hour to busywork."
- "So I handed all of it to n8n. The sheet is my content calendar, and n8n is my assistant."

### Scene 3 – The big picture (1:30–2:30)
**Show:** the full canvas zoomed out. Trace the line with your cursor.
**Say:**
- "There are four stages:"
  1. "**Start and collect**: wake up at 8AM and grab the rows that are ready."
  2. "**Submit**: send each script to HeyGen and get back a video ID."
  3. "**Wait and check**: HeyGen takes a few minutes to render, so we check every 60 seconds until it's done. That's this loop at the bottom."
  4. "**Deliver**: download the video, put it in Google Drive, and update the sheet."

### Scene 4 – The Google Sheet (2:30–3:15)
**Show:** the sheet columns: the script text, the status column, and the columns that get filled in later (for example the Drive link).
**Say:**
- "This sheet controls everything. A row only gets picked up when its status is *Ready for Video*."
- "That means I can write scripts days ahead and only flip them to ready when I'm happy with them."
- "When the workflow finishes, it changes the status to *Ready to Post*, so the same row never gets made twice."

### Scene 5 – Schedule Trigger + Read Rows (3:15–4:15)
**Show:** open **Schedule Trigger (8AM Daily)**, then **Read Rows — Ready for Video** and its filter. Run it and show the rows it returns.
**Say:**
- "The Schedule Trigger is the alarm clock. Every day at 8AM, it starts the workflow."
- "Next, the Google Sheets node reads only the rows marked *Ready for Video*. Everything else is ignored."
- "Each row becomes one item, and every node after this runs once per row. Three rows means three videos."

### Scene 6 – Submit to HeyGen + Extract Video ID (4:15–5:30)
**Show:** open **Submit to HeyGen API**: the POST URL, the API key header (**blur your key!**), and the JSON body with the avatar, voice and script mapped from the sheet. Then open **Extract Video ID** and show its output.
**Say:**
- "This HTTP Request node talks to HeyGen's API. It sends the script from the sheet, plus which avatar and voice to use."
- "My API key goes in the header. Keep it in n8n credentials, not pasted into the node, and never show it on screen."
- "HeyGen doesn't return the video straight away. It returns a **video ID**, like a ticket number at a deli counter."
- "The Code node, *Extract Video ID*, pulls that ID out and keeps it with the row, so we know which video belongs to which script."

### Scene 7 – The wait-and-check loop (5:30–7:30)
**Show:** trace the loop: **Wait 60 Seconds → Poll HeyGen Status → Check Status + Build State → Is Video Done?** Point at the *false* line going back to the Wait node. Open an execution and show it going round the loop a few times.
**Say:**
- "This is the most important part of the workflow."
- "Rendering an AI video takes a few minutes. If we asked for it immediately, it wouldn't exist yet."
- "So we **wait 60 seconds**, then **poll**: we ask HeyGen, *'Is ticket number such-and-such ready?'*"
- "*Check Status + Build State* reads the answer. It could be still processing, completed, or failed. It also keeps the video URL and the row's details together for the next steps."
- "Then the IF node, *Is Video Done?*, decides:"
  - "**True**: the video is ready, so we move on and deliver it."
  - "**False**: not ready yet, so we go back round, wait another 60 seconds, and ask again."
- "Why 60 seconds? Checking every second would waste API calls, and HeyGen might rate-limit us. A minute is a good balance."
- Honest tip: "A loop like this needs a way out. If HeyGen reports *failed*, or it takes too long, you don't want it looping forever. Count the attempts in the Code node and stop after, say, 20 tries, or mark the row as *Failed* in the sheet."

### Scene 8 – Download, upload, update (7:30–9:00)
**Show:** open **Download Video from HeyGen** (response format set to file), then **Upload Video to Google Drive** (target folder, file name), then **Update Sheet — Ready to Post**. Finish by showing the video in Drive and the updated row.
**Say:**
- "Once the video is done, HeyGen gives us a download link. This HTTP Request downloads the actual video file."
- "Next, the Google Drive node uploads it to my content folder. I name the file after the row, so it's easy to find."
- "Finally, we update the same row in the sheet: status becomes *Ready to Post*, and I save the Drive link next to it."
- "When I open my sheet in the morning, I can see exactly which videos are ready and click straight through to them."

### Scene 9 – Live run (9:00–10:15)
**Show:** add a new row with a short script, set it to *Ready for Video*, and click **Execute Workflow**. Speed up the waiting part. Show the green nodes, the video in Drive, and the updated row.
**Say:**
> "Let's watch it happen. I'll add a quick script, mark it ready and run it. It submits, waits, checks, waits, checks... and there it is. The video is in Drive, and the sheet says *Ready to Post*."

### Scene 10 – Ideas to extend it (10:15–11:00)
**Say:**
- "Add a Telegram or Slack message so you get a ping when videos are ready."
- "Add an error path that marks the row *Failed* and saves the reason."
- "Go one step further and auto-post to TikTok, YouTube Shorts or Instagram from the *Ready to Post* rows."
- "Or let AI write the scripts too, and put them in the sheet for you to approve."

### Scene 11 – Outro (11:00–11:30)
**Say:**
> "So that's it: one Google Sheet, one daily trigger, and n8n does the rest. You write the ideas; the workflow does the busywork. If you want the workflow file, it's linked below. Like and subscribe for more automations, and tell me in the comments what you want me to automate next."

---

## Recording checklist
- [ ] Blur or hide your HeyGen API key and any Google account emails.
- [ ] Have 1–2 test rows ready in the sheet before recording.
- [ ] Run the workflow once before recording so a finished execution is ready to show in **Executions**.
- [ ] Speed up the waiting parts in editing (HeyGen renders take a few minutes).
- [ ] Zoom in on each node when you open it. The canvas text is small on screen.
