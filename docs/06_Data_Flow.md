\# 06\_Data\_Flow.md



\# BahuvuNewsAI — Data Flow Architecture



Version: v1.0

Project: BahuvuNewsAI

Owner: BAHUVU News



\---



\## 1. Purpose



This document defines how data moves through the BahuvuNewsAI system from raw news input to final publishable video output.



The goal is to ensure that every module has a clear input, output, responsibility, and handoff point.



\---



\## 2. High-Level Data Flow



```text

News Sources

&#x20;   ↓

News Collection Layer

&#x20;   ↓

Article Model

&#x20;   ↓

Validation and Deduplication

&#x20;   ↓

Editorial Orchestrator

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

Quality Review

&#x20;   ↓

Publishing Package

&#x20;   ↓

YouTube Upload

```



\---



\## 3. Source Data Inputs



BahuvuNewsAI may receive news from multiple source types.



\### 3.1 Supported Input Sources



```text

RSS feeds

News websites

Manual editor input

Government/public updates

Press releases

Verified social media posts

Existing article links

```



\### 3.2 Raw Input Fields



Each raw news item should contain:



```text

source\_name

source\_url

title

summary

published\_at

category

location

image\_url

language

raw\_content

```



Some fields may be missing at collection time, but must be normalized before editorial processing.



\---



\## 4. Article Model Flow



All collected news must be converted into the unified article model.



```text

RawNewsItem

&#x20;   ↓

normalize\_article()

&#x20;   ↓

Article

```



The Article model becomes the central data structure used across the system.



\### 4.1 Article Core Fields



```text

article\_id

title

summary

content

category

location

source\_name

source\_url

published\_at

image\_path

language

status

```



\### 4.2 Article Status Flow



```text

collected

&#x20;   ↓

validated

&#x20;   ↓

approved

&#x20;   ↓

scripted

&#x20;   ↓

translated

&#x20;   ↓

voiced

&#x20;   ↓

rendered

&#x20;   ↓

published

```



\---



\## 5. Collection Layer Data Flow



The collection layer gathers raw news and passes it into the model layer.



```text

News Source

&#x20;   ↓

collector\_agent

&#x20;   ↓

raw\_news\_items

&#x20;   ↓

article\_model.py

&#x20;   ↓

normalized\_articles

```



Responsibilities:



```text

Fetch news

Extract title and summary

Extract image URL

Extract source metadata

Assign preliminary category

Store raw source reference

```



The collection layer must not create final editorial content. It only collects and structures information.



\---



\## 6. Validation and Deduplication Flow



Before editorial selection, all articles must pass validation.



```text

normalized\_articles

&#x20;   ↓

validation\_agent

&#x20;   ↓

deduplication\_agent

&#x20;   ↓

validated\_articles

```



Validation checks:



```text

Is source available?

Is title meaningful?

Is content not empty?

Is URL valid?

Is article recent enough?

Is category usable?

Is duplicate already present?

```



Duplicate detection may compare:



```text

title similarity

source URL

published date

location

key entities

```



Invalid or duplicate articles should be marked, not silently deleted.



\---



\## 7. Editorial Orchestrator Flow



The editorial orchestrator decides which stories move forward.



```text

validated\_articles

&#x20;   ↓

editorial\_orchestrator

&#x20;   ↓

ranked\_articles

&#x20;   ↓

approved\_story\_list

```



Selection factors:



```text

public importance

regional relevance

freshness

source credibility

category balance

visual availability

audience value

```



Output:



```text

approved\_story\_list

editorial\_notes

priority\_order

```



\---



\## 8. Script Generation Flow



Approved articles are converted into narration scripts.



```text

approved\_article

&#x20;   ↓

script\_agent

&#x20;   ↓

english\_script

```



Script output should include:



```text

headline

anchor\_intro

main\_script

closing\_line

duration\_estimate

tone

```



The script must be clear, neutral, factual, and suitable for spoken news delivery.



\---



\## 9. Telugu Translation Flow



English scripts are translated into Telugu.



```text

english\_script

&#x20;   ↓

translation\_agent

&#x20;   ↓

telugu\_script

```



Translation goals:



```text

Natural Telugu

Newsreader-friendly phrasing

No unnecessary literal translation

Preserve factual meaning

Preserve names and places accurately

```



The Telugu script should be ready for voice generation or human reading.



\---



\## 10. Voice Generation Flow



The approved Telugu script is converted into audio.



```text

telugu\_script

&#x20;   ↓

voice\_agent

&#x20;   ↓

voice\_audio\_file

```



Audio metadata:



```text

audio\_path

duration\_seconds

voice\_name

language

script\_id

created\_at

```



The voice file must be linked back to the article or story package.



\---



\## 11. Graphics Generation Flow



Graphics are generated using article data and visual assets.



```text

approved\_article

&#x20;   ↓

image\_loader

&#x20;   ↓

news\_template

&#x20;   ↓

final\_graphic\_generator

&#x20;   ↓

final\_news\_graphic.png

```



Graphics input:



```text

title

summary

category

location

image\_path

published\_at

branding

```



Graphics output:



```text

headline card

news image layout

category badge

footer/header

final graphic PNG

```



Current output path:



```text

outputs/graphics/final\_news\_graphic.png

```



\---



\## 12. Video Assembly Flow



The video system combines scripts, voice, graphics, and music.



```text

story\_package

&#x20;   ↓

video\_assembler

&#x20;   ↓

final\_video.mp4

```



Video inputs:



```text

voice\_audio\_file

final\_news\_graphic

background\_music

intro\_clip

outro\_clip

lower\_third

watermark

```



Video output:



```text

outputs/final/bahuvu\_news\_episode.mp4

```



\---



\## 13. Publishing Package Flow



Before upload, each episode requires a publishing package.



```text

final\_video.mp4

&#x20;   ↓

publishing\_agent

&#x20;   ↓

youtube\_package

```



Publishing package contains:



```text

video\_file

title

description

tags

thumbnail

category

language

publish\_date

visibility

```



\---



\## 14. YouTube Upload Flow



```text

youtube\_package

&#x20;   ↓

youtube\_upload\_agent

&#x20;   ↓

uploaded\_video\_url

```



Upload result should store:



```text

youtube\_video\_id

youtube\_url

upload\_status

published\_at

error\_message

```



\---



\## 15. Error Handling Flow



Every major stage must return a clear status.



```text

success

warning

failed

skipped

needs\_review

```



Error records should include:



```text

module\_name

article\_id

stage

error\_type

error\_message

created\_at

recommended\_action

```



The system should never fail silently.



\---



\## 16. Review and Approval Gates



Human review may be required at key points.



```text

After article selection

After script generation

After Telugu translation

After final video rendering

Before YouTube upload

```



Approval states:



```text

pending\_review

approved

rejected

needs\_revision

```



\---



\## 17. Data Storage Strategy



Recommended storage folders:



```text

data/raw/

data/processed/

data/articles/

data/scripts/

data/translations/

outputs/audio/

outputs/graphics/

outputs/video/

outputs/final/

logs/

```



Each generated asset should be traceable to its source article.



\---



\## 18. Complete End-to-End Flow



```text

1\. Collect news

2\. Normalize into Article model

3\. Validate source and content

4\. Remove duplicates

5\. Rank stories editorially

6\. Approve selected stories

7\. Generate English script

8\. Translate to Telugu

9\. Generate voice audio

10\. Generate graphics

11\. Assemble video

12\. Create thumbnail

13\. Build YouTube metadata

14\. Human final review

15\. Upload or schedule publishing

16\. Store publishing result

```



\---



\## 19. Core Principle



BahuvuNewsAI must follow a clean, traceable, architecture-first data flow.



Every output should answer:



```text

Where did this data come from?

Which module created it?

Which article does it belong to?

Was it reviewed?

Is it ready for publishing?

```



This ensures the system can grow from a single test video into a professional, repeatable news production pipeline.



\---



\## 20. Current Implementation Status



Current completed foundation:



```text

Article model exists

Graphics generation exists

Broadcast layout exists

Text engine exists

Final graphic generator exists

Editorial orchestrator exists

Technical architecture documents exist

```



Next implementation areas:



```text

News source collection

Persistent article storage

Script generation

Telugu translation

Voice generation

Video assembly

Publishing package generation

YouTube upload automation

```



\---



End of document.



