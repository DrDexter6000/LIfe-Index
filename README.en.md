# Life Index | 人生索引

<div align="center">

**English** | [简体中文](./README.md)

</div>

<p align="center">
  <img src="https://img.shields.io/badge/Philosophy-Personal_Chronicle-ff6b6b" alt="Philosophy">
  <img src="https://img.shields.io/badge/Storage-Offline_First-4ecdc4" alt="Offline First">
  <img src="https://img.shields.io/badge/Interaction-Natural_Language-ffe66d" alt="Natural Language">
</p>

> **Not a knowledge base. A personal chronicle.**  
> **Optimized not for productivity, but for retrieving life's fragments.**

---

## 🎉 Before We Begin

This is my first GitHub repository.

I didn't create this to show off my coding skills. I created it to build a **Personal Life Archive** for myself — a place to keep my own life fragments, including that bittersweet ache when I stumble upon photos of my daughter at age two.    
> I want to remember not just how she grew, but how I felt. The weight of her small body in my arms. The moment she ran to the balcony, opened my cigarette pack, and handed me one with her clumsy little hands — not knowing what it was, just imitating the one she loved most.    
> And if possible, I hope to pass this **record of my whole life** down to her one day. Long after I'm gone, she can open it like a faded, yellowed book — recalling her father's love in every line, and perhaps finding a bit of his hard-won wisdom to guide her.

**🎯 My belief is that ——**    

> —— **Do you still remember what drove that decisive choice you made ten years ago?**    
> —— **Since when do only politicians and the wealthy get to hire writers for their memoirs?**          
> —— **Would you like to leave the handbook of life wisdom to your kids, a collection of mistakes & lessons**       

**This is a digital asset for us common people.**

---

## 📖 What is Life Index?

**Life Index** is **Agent-first.** **Offline by design.**

In this age of AI and cloud everything, I took a counter-intuitive path: **No cloud sync. No feature bloat. No automation traps.** Just:

> **Speak naturally about your life, your thoughts, your feelings, the books you read, the ideas you share. Let the Agent organize. Retrieve your memories through clear indexes.**

### What does a real Life Index entry look like?

<details>
<summary>📎 Example: Missing the Diaper Hero (Click to expand)</summary>

```yaml
---
title: "Missing the Diaper Hero"
date: 2026-03-04T19:43:02
location: "Lagos, Nigeria"
weather: "Sunny with scattered showers"
mood: ["Nostalgic", "Warm", "Melancholy"]
people: ["Tuantuan (my daughter)"]
tags: ["Parenthood", "Memory", "Growth", "Bittersweet"]
project: "LifeIndex"
topic: ["think", "relation"]
abstract: "Looking at old photos of my daughter. Missing the 2-year-old diaper-clad hero. A meditation on time and fatherhood."
attachments: ["video_of_her_at_2.mp4"]
---

# Missing the Diaper Hero

*Note: "NiaoPiaXia" (尿片侠, literally "Diaper Hero") was our affectionate nickname for my daughter during her diaper days — describing the clumsy bravery of a 2-year-old exploring the world.*

---

While organizing old files, I came across photos of Tuantuan as a baby. That little 2-year-old Diaper Hero.

A sudden sadness hit me — I miss that tiny human so much. I wish I could see her again, just once more. I wish I could hold that little lump of warmth in my arms again.

There's an illusion that the 2-year-old Tuantuan was my baby, and the current Tuantuan is still my heart — but they feel like different people?

Before age three, babies are like small animals, driven entirely by instinct. Hungry, sleepy, playful, wanting mama and papa — none of it goes through rational thought.

And the world was so dangerous for her then. She knew nothing, understood nothing. What fascinated her most was every move Mama and Papa made. She followed us everywhere, mimicking our every gesture.

I still remember her waddling to the balcony, opening my cigarette pack, and handing me one — she didn't know what she was doing, but she was summarizing her observations of Dad's habits [laughs with tears].

At three, she started kindergarten. She began interacting with teachers and friends. She became a child — with her own thoughts, personality, even plans. Mama and Papa were no longer the sole center of her universe.

The Tuantuan after three is still the most precious existence in the universe — but truly, she is no longer that babbling infant. That Diaper Hero who captivated my soul has grown up.

I both wish our family could stay forever in that time when she was 2 — and hope she grows up to experience an even more beautiful world.

All in all, little bump, Dad misses you.

This one's for you, Tuantuan.
```
</details>

This is Life Index's mission: **To remember exactly how that felt — forever beyond big tech's reach.**

---

## 🏛️ Core Architecture

### 1. Agent-First
No complex tagging systems to learn. No software interfaces to master. Just tell your Agent:
> "Log this: I saw old photos of my daughter today and felt that bittersweet ache for when she was two."

The Agent extracts metadata automatically (time, location, people, emotions, tags) and generates structured Markdown files.

### 2. Offline-First / Data Sovereignty
- **100% Local Storage**: All data lives as Markdown + YAML files on your hard drive
- **Human-Readable**: Even in 20 years without Life Index, you can read the plain text
- **Absolute Privacy**: No cloud services. Your memory of the Diaper Hero belongs only to you

### 3. Three-Layer Taxonomy
No complex folder nesting. Just three clear dimensions:

| Level | Dimension | Examples |
|:---:|:---:|:---:|
| **L1 Topic** | Knowledge Domain | `think` (Reflection), `create` (Creation), `relation` (Relationships) |
| **L2 Project** | Goal Domain | `LifeIndex` (This project), `Fatherhood` (My journey as a dad) |
| **L3 Tag** | Feature Domain | `Parenthood`, `Memory`, `Bittersweet`, `DiaperHero` |

Want to find "all my melancholic memories about my daughter"? Search `Tuantuan` + `Melancholy` — regardless of which project they belong to.

---

## 🚀 Quick Start

### Prerequisites
- An AI Agent with file operation capabilities
- A local directory (suggested: `~/Documents/Life-Index`)

### Directory Structure
```
Life-Index/
├── journals/          # Main journal directory (organized by year/month)
│   └── 2026/
│       └── 03/
│           └── life-index_2026-03-04_002.md
├── attachments/       # Photos, videos, voice memos
│   └── 2026/03/
│       └── [video_file].mp4
└── by-topic/          # Auto-generated indexes
    ├── topic_think.md
    ├── project_LifeIndex.md
    └── tag_Parenthood.md
```

### Write Your First Entry

Simply speak to your Agent:

> "March 5th, 2026, Chongqing, sunny. I want to record why I started Life Index. It's not to build another Notion or Obsidian — it's to help ordinary people like me organize life fragments. I want to record the details of my fatherhood, that bittersweet feeling, like when my daughter imitated me smoking at age two..."

The Agent will:
1. Generate a Markdown file with frontmatter
2. Auto-extract time, location, weather, tags
3. Update monthly summaries and topic indexes
4. Keep it plain text, forever readable

---

## 📚 Documentation Navigation

Life Index follows the **SSOT (Single Source of Truth)** principle:

| Document | Content | When to Read |
|:---:|:---:|:---:|
| **[HANDBOOK.md](./HANDBOOK.md)** | Vision, architecture, core principles | You want to understand "why it's designed this way" |
| **[AGENT.md](./AGENT.md)** | Agent instructions, tool interfaces, workflows | You're a developer implementing Agent functionality |
| **[CHANGELOG.md](./CHANGELOG.md)** | Major decision records, version evolution | You want to understand project history |

---

## 🎯 Design Bottom Line

```
Prefer simplicity over complexity
Prefer manual maintenance over automation traps
Prefer reliability over performance
```

We deliberately DON'T do:
- ❌ Cloud sync (You can backup with your own cloud drive, but we don't force it)
- ❌ Rich text editing (Markdown is enough to express "Missing the Diaper Hero")
- ❌ Real-time collaboration (This is YOUR life, not a team's)
- ❌ AI auto-summarization (We index, but we don't think for you)

---

## 🌱 Who is this for?

- **New Parents**: Who want to record their own experience of parenthood — that bittersweet ache, the wonder, the heartbreak — not just baby's milestones
- **Digital Nomads**: Moving between cities, needing to record locations and local states of mind
- **Long-termists**: Wanting a system that lasts 30 years, not chasing the latest productivity tool
- **Privacy Conscious**: Believing your life details shouldn't be training data for cloud services
- **Ordinary People**: Who believe their daily life fragments are worth preserving, even without being "productive"

---

## 🤝 Contributing

Currently, Life Index is in personal-use stage. If you resonate with the "Personal Life Archive" philosophy, welcome to:

1. **Open Issues**: Share your use cases, or report bugs
2. **Improve Docs**: Help with multilingual versions
3. **Share Stories**: If Life Index helped you preserve an important moment, consider sharing (anonymized)

---

## 📜 License

Apache License 2.0 — Your life data belongs to you. So does this code.

---

> *"I both wish our family could stay forever in that time when she was 2 — and hope she grows up to experience an even more beautiful world. All in all, little bump, Dad misses you. This one's for you, Tuantuan."*
> 

> *—— From the first Life Index entry, March 4, 2026, Lagos. Not a record of her growth. A record of my love.*







