\# BahuvuNewsAI Project Structure

\## Document 04 – Project Structure



\*\*Document Version:\*\* 1.0



\*\*Project:\*\* BahuvuNewsAI



\*\*Status:\*\* Approved Architecture



\---



\# Purpose



This document defines the official folder hierarchy and module organization for BahuvuNewsAI.



Every source file, asset, configuration file, document, test, and output shall have a clearly defined location.



No module should exist outside this structure without architectural approval.



\---



\# Design Principles



The project structure follows these principles:



\- Separation of responsibilities

\- High cohesion

\- Low coupling

\- Easy navigation

\- Scalable architecture

\- Simple deployment

\- Easy testing

\- Future extensibility



\---



\# Root Directory



```

BahuvuNewsAI/

```



Contains the complete project.



\---



\# Top-Level Structure



```

BahuvuNewsAI/



agents/

assets/

config/

data/

docs/

logs/

outputs/

scripts/

tests/



main.py

requirements.txt

README.md

PROJECT\_MASTER.md

```



\---



\# Directory Responsibilities



\## agents/



Contains all business logic.



This is the heart of the application.



Example modules:



```

article\_model.py

news\_pipeline.py

story\_ranking.py

duplicate\_detector.py

editorial\_validator.py

script\_generator.py

translator.py

voice\_generator.py

video\_composer.py

youtube\_publisher.py

```



\---



\## assets/



Contains static resources.



Example:



```

fonts/

icons/

images/

logos/

music/

overlays/

templates/

```



Assets are read-only during normal execution.



\---



\## config/



Contains configuration files.



Example:



```

settings.yaml



logging.yaml



api\_keys.example.yaml



categories.json

```



No hard-coded settings should exist inside business modules.



\---



\## data/



Contains runtime data.



Example:



```

cache/



rss/



downloads/



processed/



translations/



database/

```



Data may be recreated.



\---



\## docs/



Architecture and documentation.



Contains:



```

Project Vision



Architecture



Requirements



Technical Design



Standards



Testing



Roadmap



Decision Records

```



Documentation must stay synchronized with implementation.



\---



\## logs/



Application logs.



Example:



```

system.log



pipeline.log



errors.log



youtube.log

```



Logs should rotate automatically.



\---



\## outputs/



Generated artifacts.



Example:



```

graphics/



audio/



video/



thumbnails/



subtitles/



archives/

```



All generated media belongs here.



\---



\## scripts/



Utility scripts.



Example:



```

setup.py



download\_fonts.py



cleanup.py



benchmark.py

```



These are development or maintenance tools.



\---



\## tests/



Automated tests.



Example:



```

unit/



integration/



end\_to\_end/

```



Every major module should eventually have test coverage.



\---



\# Python Module Organization



Modules are grouped by responsibility.



\## News Collection



```

rss\_fetcher.py



api\_fetcher.py



web\_fetcher.py



news\_pipeline.py

```



\---



\## Editorial



```

article\_model.py



duplicate\_detector.py



story\_cluster.py



story\_ranking.py



editorial\_validator.py



fact\_verifier.py

```



\---



\## Content Generation



```

script\_generator.py



translator.py



headline\_generator.py



summary\_generator.py

```



\---



\## Media Production



```

graphics\_engine.py



news\_template.py



photo\_layout.py



video\_composer.py



voice\_generator.py

```



\---



\## Publishing



```

youtube\_publisher.py



scheduler.py



analytics.py

```



\---



\# Naming Conventions



Python files:



snake\_case



Classes:



PascalCase



Functions:



snake\_case



Constants:



UPPER\_CASE



Private helpers:



\_prefix()



\---



\# Import Rules



Allowed:



```

main.py



↓



agents



↓



helpers

```



Avoid circular imports.



Dependencies should point downward.



\---



\# File Size Guidelines



Recommended:



200–400 lines



Acceptable:



400–700 lines



Avoid:



1000+ line modules.



Large modules should be split by responsibility.



\---



\# Documentation Rules



Every module should contain:



Purpose



Responsibilities



Inputs



Outputs



Dependencies



Example usage



Version



\---



\# Future Growth



The structure supports:



100+ Python modules



Multiple AI providers



Cloud deployment



Microservices



Web dashboard



Plugin system



Enterprise edition



\---



\# Architecture Rule



Every new file must have a defined architectural location before implementation.



No "temporary" modules should remain permanently in the project.



\---



\# Summary



A disciplined project structure is essential for maintaining a professional, scalable, and long-lived software system.



This directory organization provides a stable foundation for BahuvuNewsAI as it evolves from a development project into a production-ready AI newsroom platform.

