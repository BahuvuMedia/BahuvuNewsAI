\# 07\_System\_Architecture.md



\# BahuvuNewsAI — System Architecture



Version: v1.0

Project: BahuvuNewsAI

Owner: BAHUVU News



\---



\## 1. Purpose



This document defines the complete system architecture of BahuvuNewsAI.



BahuvuNewsAI is designed as an agentic AI-powered news production platform that can collect news, process articles, generate scripts, translate content into Telugu, create graphics, generate voice, assemble videos, and prepare publishable news packages for YouTube.



This document acts as the master blueprint for the project.



\---



\## 2. System Vision



BahuvuNewsAI should operate as a professional digital newsroom automation system.



The system must support:



```text

News discovery

Article normalization

Editorial selection

Fact-aware scripting

Telugu news translation

Voice generation

Broadcast graphics

Video assembly

Thumbnail creation

Publishing preparation

YouTube upload automation

Human review gates

```



The goal is not only to automate tasks, but to create a reliable, repeatable, traceable news production pipeline.



\---



\## 3. Architecture Philosophy



The system follows these core principles:



```text

Architecture before implementation

One module, one responsibility

Clear input and output contracts

Human review before publishing

Traceability from source to final video

Replaceable AI providers

Stable file structure

Incremental production readiness

```



BahuvuNewsAI must avoid random scripts and disconnected modules. Every file should belong to a defined layer of the system.



\---



\## 4. High-Level System Architecture



```text

+--------------------------------------------------+

|                  User / Editor                   |

+--------------------------------------------------+

&#x20;                        |

&#x20;                        v

+--------------------------------------------------+

|              Editorial Control Layer             |

+--------------------------------------------------+

&#x20;                        |

&#x20;                        v

+--------------------------------------------------+

|                 Agent Layer                      |

| Collection | Validation | Script | Voice | Video |

+--------------------------------------------------+

&#x20;                        |

&#x20;                        v

+--------------------------------------------------+

|                 Core Model Layer                 |

| Article | Story Package | Script | Media Assets |

+--------------------------------------------------+

&#x20;                        |

&#x20;                        v

+--------------------------------------------------+

|                Processing Layer                  |

| Graphics | Audio | Translation | Video Assembly |

+--------------------------------------------------+

&#x20;                        |

&#x20;                        v

+--------------------------------------------------+

|                 Storage Layer                    |

| Data | Outputs | Logs | Assets | Config          |

+--------------------------------------------------+

&#x20;                        |

&#x20;                        v

+--------------------------------------------------+

|                Publishing Layer                  |

| YouTube Package | Upload | Status Tracking       |

+--------------------------------------------------+

```



\---



\## 5. Layered Architecture



BahuvuNewsAI is divided into the following layers:



```text

1\. Input Layer

2\. Normalization Layer

3\. Editorial Layer

4\. AI Processing Layer

5\. Media Generation Layer

6\. Assembly Layer

7\. Review Layer

8\. Publishing Layer

9\. Storage Layer

10\. Configuration and Logging Layer

```



Each layer must be independently understandable and testable.



\---



\## 6. Input Layer



The input layer collects raw news from external or manual sources.



Supported sources:



```text

RSS feeds

News websites

Manual editor entry

Public announcements

Government updates

Press releases

Verified social media posts

Existing news URLs

```



The input layer should not make final editorial decisions.



Its responsibility is only to collect structured raw information.



\---



\## 7. Normalization Layer



The normalization layer converts raw news into a standard article structure.



Main file:



```text

agents/article\_model.py

```



Expected normalized output:



```text

Article

```



The Article model should act as the central unit of news data throughout the system.



\---



\## 8. Editorial Layer



The editorial layer decides what is important enough to become a story.



Main responsibility:



```text

Select, rank, approve, reject, or hold stories for review.

```



Current related file:



```text

main.py

```



Future related files:



```text

agents/editorial\_orchestrator.py

agents/story\_ranker.py

agents/editorial\_policy.py

agents/fact\_review.py

```



Editorial rules must prioritize:



```text

Public importance

Accuracy

Source reliability

Regional relevance

Audience usefulness

Neutral tone

Timeliness

```



\---



\## 9. Agent Layer



BahuvuNewsAI is designed as a multi-agent system.



Core agents:



```text

News Collection Agent

Validation Agent

Deduplication Agent

Editorial Agent

Script Agent

Telugu Translation Agent

Voice Agent

Graphics Agent

Video Assembly Agent

Publishing Agent

Advertisement Agent

```



Each agent must have:



```text

Clear input

Clear output

Defined responsibility

Error status

Review status if needed

```



\---



\## 10. Core Data Models



The system should be built around stable data models.



Primary models:



```text

Article

StoryPackage

NewsScript

TranslationResult

VoiceAsset

GraphicAsset

VideoAsset

PublishingPackage

UploadResult

```



These models allow the system to pass data cleanly between modules.



\---



\## 11. Current Implemented Core Modules



Current stable foundation:



```text

agents/article\_model.py

agents/layout.py

agents/broadcast\_layout.py

agents/news\_template.py

agents/final\_graphic\_generator.py

agents/header.py

agents/footer.py

agents/category\_badge.py

agents/headline\_renderer.py

agents/summary\_renderer.py

agents/photo\_layout.py

agents/text\_engine.py

agents/image\_loader.py

agents/fonts.py

agents/theme.py

```



These modules form the current graphics and article foundation.



\---



\## 12. Graphics Architecture



The graphics system follows a modular broadcast layout design.



```text

layout.py

&#x20;   ↓

broadcast\_layout.py

&#x20;   ↓

news\_template.py

&#x20;   ↓

final\_graphic\_generator.py

&#x20;   ↓

outputs/graphics/final\_news\_graphic.png

```



Graphics responsibilities:



```text

Canvas definition

Safe areas

Header

Footer

Category badge

Headline rendering

Summary rendering

Photo rendering

Final composition

```



The graphics system should remain independent from the news collection and publishing layers.



\---



\## 13. Text Rendering Architecture



Text rendering is handled by reusable text modules.



Current files:



```text

agents/text\_engine.py

agents/headline\_renderer.py

agents/summary\_renderer.py

agents/fonts.py

```



Responsibilities:



```text

Text wrapping

Font sizing

Line fitting

Headline rendering

Summary rendering

Telugu font support

```



Text rendering must support both English and Telugu output.



\---



\## 14. Media Generation Architecture



Media generation includes:



```text

Graphics

Voice

Background music

Video assembly

Thumbnail creation

```



Future modules:



```text

agents/voice\_generator.py

agents/video\_assembler.py

agents/thumbnail\_generator.py

agents/music\_manager.py

agents/asset\_manager.py

```



All generated media must be saved under the outputs directory.



\---



\## 15. AI Provider Architecture



BahuvuNewsAI should support multiple AI providers through an abstraction layer.



Supported provider types may include:



```text

Google AI Studio

OpenRouter

GitHub Models

Local models

Future paid APIs

```



The application should not hardcode one AI provider into business logic.



Recommended future files:



```text

agents/ai\_provider.py

agents/llm\_client.py

agents/prompt\_manager.py

agents/model\_router.py

```



Provider abstraction should support:



```text

Model selection

Fallback provider

Cost control

Rate limit handling

Retry handling

Prompt logging

Response validation

```



\---



\## 16. Data Flow Architecture



The system follows this end-to-end flow:



```text

News Source

&#x20;   ↓

Collection Agent

&#x20;   ↓

Article Model

&#x20;   ↓

Validation

&#x20;   ↓

Deduplication

&#x20;   ↓

Editorial Selection

&#x20;   ↓

Script Generation

&#x20;   ↓

Telugu Translation

&#x20;   ↓

Voice Generation

&#x20;   ↓

Graphics Generation

&#x20;   ↓

Video Assembly

&#x20;   ↓

Review

&#x20;   ↓

Publishing Package

&#x20;   ↓

YouTube Upload

```



This flow is defined in detail in:



```text

docs/06\_Data\_Flow.md

```



\---



\## 17. Storage Architecture



Recommended folder structure:



```text

data/

&#x20;   raw/

&#x20;   processed/

&#x20;   articles/

&#x20;   scripts/

&#x20;   translations/



assets/

&#x20;   backgrounds/

&#x20;   fonts/

&#x20;   icons/

&#x20;   images/

&#x20;   logos/

&#x20;   music/

&#x20;   overlays/

&#x20;   sounds/

&#x20;   templates/



outputs/

&#x20;   audio/

&#x20;   graphics/

&#x20;   video/

&#x20;   final/



logs/



docs/

```



Storage rules:



```text

Raw data should be preserved

Processed data should be traceable

Generated files should be linked to source articles

Logs should capture failures clearly

Final outputs should be reviewable before publishing

```



\---



\## 18. Configuration Architecture



Configuration should not be scattered across modules.



Configuration should include:



```text

Project paths

Output paths

Branding settings

AI provider settings

YouTube settings

Language settings

Voice settings

Graphics settings

Logging settings

```



Recommended future files:



```text

agents/config.py

.env

config/settings.json

config/providers.json

config/publishing.json

```



Sensitive data must never be committed to GitHub.



\---



\## 19. Logging Architecture



Every major step should log status.



Log levels:



```text

INFO

WARNING

ERROR

SUCCESS

DEBUG

```



Important events to log:



```text

Article collected

Article validated

Duplicate detected

Story approved

Script generated

Translation completed

Voice generated

Graphic created

Video rendered

Upload completed

Upload failed

```



Recommended future file:



```text

agents/logger.py

```



\---



\## 20. Error Handling Architecture



The system should never fail silently.



Every agent should return a structured status:



```text

success

warning

failed

skipped

needs\_review

```



Error record fields:



```text

module\_name

stage

article\_id

error\_type

error\_message

created\_at

recommended\_action

```



Failed items should be saved for review instead of being lost.



\---



\## 21. Review Gate Architecture



Human review is required before publishing.



Recommended review gates:



```text

Article selection review

Script review

Telugu translation review

Voice review

Final video review

YouTube metadata review

```



Approval states:



```text

pending\_review

approved

rejected

needs\_revision

```



This is critical because BahuvuNewsAI is a news system, not just a content generator.



\---



\## 22. Publishing Architecture



Publishing should be separated from video creation.



Publishing package:



```text

video\_file

thumbnail\_file

youtube\_title

youtube\_description

tags

language

category

visibility

scheduled\_time

```



Future module:



```text

agents/youtube\_publisher.py

```



The publishing agent should only upload content that has passed final review.



\---



\## 23. Advertisement Agent Architecture



The Advertisement Agent should support monetization without damaging editorial integrity.



Responsibilities:



```text

Generate sponsor slots

Create ad script sections

Insert ad breaks where appropriate

Prepare sponsor metadata

Keep ads separate from news facts

```



Rules:



```text

Ads must be clearly separated from editorial content

Ads must not alter news meaning

Sponsored content must be labeled

Ad insertion must not reduce credibility

```



Future file:



```text

agents/ad\_agent.py

```



\---



\## 24. Security Architecture



Security priorities:



```text

Protect API keys

Protect YouTube credentials

Avoid publishing without approval

Avoid unverified claims

Avoid prompt injection from raw sources

Avoid committing secrets to GitHub

```



Sensitive information should be stored in:



```text

.env

local config files

secure environment variables

```



Never store secrets in:



```text

Python files

Markdown documents

Git commits

Public logs

```



\---



\## 25. Deployment Architecture



Initial deployment can remain local on Windows.



Current development environment:



```text

Windows

PowerShell

Python

Git

Notepad

GitHub repository

```



Future deployment options:



```text

Local scheduled runner

Cloud VM

GitHub Actions for tests

Containerized deployment

Newsroom dashboard

```



Deployment should happen only after the core pipeline is stable.



\---



\## 26. Testing Architecture



Each module should support:



```text

py\_compile test

Direct module run test

Sample input test

Output file check

Error case test

```



Current common command:



```powershell

python -m py\_compile agents\\module\_name.py

```



For runnable modules:



```powershell

python -m agents.module\_name

```



Testing should be performed before commit.



\---



\## 27. Development Workflow



Recommended workflow:



```text

1\. Open one file

2\. Replace with complete tested version

3\. Run py\_compile

4\. Run module test if applicable

5\. Inspect output

6\. git add

7\. git commit

8\. git push

```



This supports the project goal of reducing repeated corrections and avoiding unstable partial edits.



\---



\## 28. Git Architecture



Git commits should be meaningful and focused.



Recommended commit styles:



```text

docs: add system architecture

agents: add script generator

agents: add voice generator

graphics: improve layout rendering

video: add video assembly pipeline

fix: correct article validation

```



Each commit should represent one clear milestone.



\---



\## 29. Technology Stack



Current stack:



```text

Python

Pillow

Git

PowerShell

Markdown

GitHub

```



Planned stack may include:



```text

MoviePy or FFmpeg

YouTube Data API

LLM provider APIs

Text-to-speech engine

SQLite or JSON storage

Scheduler

Dashboard framework

```



Technology choices should remain practical and maintainable.



\---



\## 30. Scalability Strategy



BahuvuNewsAI should grow in phases.



Phase 1:



```text

Manual input

Graphics output

Basic scripting

Manual review

```



Phase 2:



```text

Automated collection

Script generation

Telugu translation

Voice generation

```



Phase 3:



```text

Video assembly

Thumbnail generation

Publishing package

```



Phase 4:



```text

YouTube upload automation

Scheduling

Dashboard

Monitoring

```



Phase 5:



```text

Multi-language support

Multiple shows

Advertisement automation

Analytics feedback loop

```



\---



\## 31. Future Directory Structure



Recommended long-term structure:



```text

BahuvuNewsAI/

&#x20;   agents/

&#x20;       collection/

&#x20;       editorial/

&#x20;       scripting/

&#x20;       translation/

&#x20;       voice/

&#x20;       graphics/

&#x20;       video/

&#x20;       publishing/

&#x20;       ads/

&#x20;       common/



&#x20;   assets/

&#x20;       fonts/

&#x20;       images/

&#x20;       logos/

&#x20;       music/

&#x20;       overlays/

&#x20;       templates/



&#x20;   config/



&#x20;   data/

&#x20;       raw/

&#x20;       processed/

&#x20;       articles/

&#x20;       scripts/

&#x20;       translations/



&#x20;   docs/



&#x20;   outputs/

&#x20;       audio/

&#x20;       graphics/

&#x20;       video/

&#x20;       final/



&#x20;   tests/



&#x20;   logs/



&#x20;   main.py

&#x20;   README.md

&#x20;   requirements.txt

```



This structure may be adopted gradually.



\---



\## 32. End-to-End Production Workflow



A complete production workflow should look like this:



```text

1\. Collect news from sources

2\. Normalize all items into Article objects

3\. Validate and remove duplicates

4\. Rank stories by editorial importance

5\. Select approved stories

6\. Generate English script

7\. Translate script into Telugu

8\. Review Telugu script

9\. Generate Telugu voiceover

10\. Generate graphics for each story

11\. Assemble final video

12\. Generate thumbnail

13\. Prepare YouTube metadata

14\. Human final review

15\. Upload or schedule video

16\. Store publishing status

```



\---



\## 33. Architectural Rules



All future development should follow these rules:



```text

Do not mix collection logic with rendering logic

Do not mix publishing logic with script generation

Do not hardcode AI providers inside business modules

Do not skip human review before publishing

Do not silently delete failed items

Do not commit secrets

Do not create duplicate modules for the same responsibility

Do not rewrite stable modules without reason

```



\---



\## 34. Current Architecture Status



Completed foundations:



```text

Graphics foundation

Broadcast layout

Text rendering

Image loading

Final graphic generation

Article model

Editorial orchestration beginning

Technical documentation

Product requirements

Module catalog

Data flow architecture

```



Next implementation targets:



```text

Persistent article storage

News collection agent

Validation agent

Deduplication agent

Script generation agent

Telugu translation agent

Voice generation agent

Video assembly agent

Publishing package agent

YouTube upload agent

```



\---



\## 35. Conclusion



BahuvuNewsAI is being designed as a professional, modular, agentic news production system.



The architecture must remain clean, traceable, and expandable.



Every future module should fit into this master architecture instead of creating isolated scripts.



The long-term goal is a publishable, repeatable, Telugu-focused news production platform capable of supporting BAHUVU News on YouTube and beyond.



\---



End of document.



