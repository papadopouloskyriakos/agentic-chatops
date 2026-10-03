# Appendix C: Quick Overview of Agentic Frameworks

> From *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems* by Antonio Gulli.
> Source: [`docs/Agentic_Design_Patterns.pdf`](../Agentic_Design_Patterns.pdf) (extracted 2026-04-23 via `pdftotext -layout`).
> Overview: [`docs/gulli-book-overview.md`](../gulli-book-overview.md).
> Our platform's status on this pattern: see [`wiki/patterns/`](../../wiki/patterns/).

---

   Randomize the order of examples from different categories to prevent overfitting.




                                                                                      26

●​ Adapt to Model Updates: Language models are constantly being updated. Be
   prepared to test your existing prompts on new model versions and adjust them to
   leverage new capabilities or maintain performance.
●​ Experiment with Output Formats: Especially for non-creative tasks, experiment
   with requesting structured output like JSON or XML.
●​ Experiment Together with Other Prompt Engineers: Collaborating with others
   can provide different perspectives and lead to discovering more effective
   prompts.
●​ CoT Best Practices: Remember specific practices for Chain of Thought, such as
   placing the answer after the reasoning and setting temperature to 0 for tasks with
   a single correct answer.
●​ Document the Various Prompt Attempts: This is crucial for tracking what works,
   what doesn't, and why. Maintain a structured record of your prompts,
   configurations, and results.
●​ Save Prompts in Codebases: When integrating prompts into applications, store
   them in separate, well-organized files for easier maintenance and version control.
●​ Rely on Automated Tests and Evaluation: For production systems, implement
   automated tests and evaluation procedures to monitor prompt performance and
   ensure generalization to new data.
Prompt engineering is a skill that improves with practice. By applying these principles
and techniques, and by maintaining a systematic approach to experimentation and
documentation, you can significantly enhance your ability to build effective agentic
systems.


Conclusion
This appendix provides a comprehensive overview of prompting, reframing it as a
disciplined engineering practice rather than a simple act of asking questions. Its
central purpose is to demonstrate how to transform general-purpose language
models into specialized, reliable, and highly capable tools for specific tasks. The
journey begins with non-negotiable core principles like clarity, conciseness, and
iterative experimentation, which are the bedrock of effective communication with AI.
These principles are critical because they reduce the inherent ambiguity in natural
language, helping to steer the model's probabilistic outputs toward a single, correct
intention. Building on this foundation, basic techniques such as zero-shot, one-shot,
and few-shot prompting serve as the primary methods for demonstrating expected
behavior through examples. These methods provide varying levels of contextual
guidance, powerfully shaping the model's response style, tone, and format. Beyond
just examples, structuring prompts with explicit roles, system-level instructions, and

                                                                                     27

clear delimiters provides an essential architectural layer for fine-grained control over
the model.

The importance of these techniques becomes paramount in the context of building
autonomous agents, where they provide the control and reliability necessary for
complex, multi-step operations. For an agent to effectively create and execute a plan,
it must leverage advanced reasoning patterns like Chain of Thought and Tree of
Thoughts. These sophisticated methods compel the model to externalize its logical
steps, systematically breaking down complex goals into a sequence of manageable
sub-tasks. The operational reliability of the entire agentic system hinges on the
predictability of each component's output. This is precisely why requesting structured
data like JSON, and programmatically validating it with tools such as Pydantic, is not a
mere convenience but an absolute necessity for robust automation. Without this
discipline, the agent’s internal cognitive components cannot communicate reliably,
leading to catastrophic failures within an automated workflow. Ultimately, these
structuring and reasoning techniques are what successfully convert a model's
probabilistic text generation into a deterministic and trustworthy cognitive engine for
an agent.

Furthermore, these prompts are what grant an agent its crucial ability to perceive and
act upon its environment, bridging the gap between digital thought and real-world
interaction. Action-oriented frameworks like ReAct and native function calling are the
vital mechanisms that serve as the agent's hands, allowing it to use tools, query APIs,
and manipulate data. In parallel, techniques like Retrieval Augmented Generation
(RAG) and the broader discipline of Context Engineering function as the agent's
senses. They actively retrieve relevant, real-time information from external knowledge
bases, ensuring the agent’s decisions are grounded in current, factual reality. This
critical capability prevents the agent from operating in a vacuum, where it would be
limited to its static and potentially outdated training data. Mastering this full spectrum
of prompting is therefore the definitive skill that elevates a generalist language model
from a simple text generator into a truly sophisticated agent, capable of performing
complex tasks with autonomy, awareness, and intelligence.


References
Here is a list of resources for further reading and deeper exploration of prompt
engineering techniques:
 1.​ Prompt Engineering, https://www.kaggle.com/whitepaper-prompt-engineering



                                                                                        28

2.​ Chain-of-Thought Prompting Elicits Reasoning in Large Language Models,
    https://arxiv.org/abs/2201.11903
3.​ Self-Consistency Improves Chain of Thought Reasoning in Language Models,
    https://arxiv.org/pdf/2203.11171
4.​ ReAct: Synergizing Reasoning and Acting in Language Models,
    https://arxiv.org/abs/2210.03629
5.​ Tree of Thoughts: Deliberate Problem Solving with Large Language Models,
    https://arxiv.org/pdf/2305.10601
6.​ Take a Step Back: Evoking Reasoning via Abstraction in Large Language Models,
    https://arxiv.org/abs/2310.06117
7.​ DSPy: Programming—not prompting—Foundation Models
    https://github.com/stanfordnlp/dspy




                                                                                29

Appendix B - AI Agentic Interactions:
From GUI to Real World environment
AI agents are increasingly performing complex tasks by interacting with digital
interfaces and the physical world. Their ability to perceive, process, and act within
these varied environments is fundamentally transforming automation,
human-computer interaction, and intelligent systems. This appendix explores how
agents interact with computers and their environments, highlighting advancements
and projects.


Interaction: Agents with Computers
The evolution of AI from conversational partners to active, task-oriented agents is
being driven by Agent-Computer Interfaces (ACIs). These interfaces allow AI to
interact directly with a computer's Graphical User Interface (GUI), enabling it to
perceive and manipulate visual elements like icons and buttons just as a human would.
This new method moves beyond the rigid, developer-dependent scripts of traditional
automation that relied on APIs and system calls. By using the visual "front door" of
software, AI can now automate complex digital tasks in a more flexible and powerful
way, a process that involves several key stages:

   ●​ Visual Perception: The agent first captures a visual representation of the
      screen, essentially taking a screenshot.
   ●​ GUI Element Recognition: It then analyzes this image to distinguish between
      various GUI elements. It must learn to "see" the screen not as a mere collection
      of pixels, but as a structured layout with interactive components, discerning a
      clickable "Submit" button from a static banner image or an editable text field
      from a simple label.
   ●​ Contextual Interpretation: The ACI module, acting as a bridge between the
      visual data and the agent's core intelligence (often a Large Language Model or
      LLM), interprets these elements within the context of the task. It understands
      that a magnifying glass icon typically means "search" or that a series of radio
      buttons represents a choice. This module is crucial for enhancing the LLM's
      reasoning, allowing it to form a plan based on visual evidence.
   ●​ Dynamic Action and Response: The agent then programmatically controls
      the mouse and keyboard to execute its plan—clicking, typing, scrolling, and
      dragging. Critically, it must constantly monitor the screen for visual feedback,

                                                                                        1

      dynamically responding to changes, loading screens, pop-up notifications, or
      errors to successfully navigate multi-step workflows.

This technology is no longer theoretical. Several leading AI labs have developed
functional agents that demonstrate the power of GUI interaction:

ChatGPT Operator (OpenAI): Envisioned as a digital partner, ChatGPT Operator is
designed to automate tasks across a wide range of applications directly from the
desktop. It understands on-screen elements, enabling it to perform actions like
transferring data from a spreadsheet into a customer relationship management (CRM)
platform, booking a complex travel itinerary across airline and hotel websites, or filling
out detailed online forms without needing specialized API access for each service.
This makes it a universally adaptable tool aimed at boosting both personal and
enterprise productivity by taking over repetitive digital chores.

Google Project Mariner: As a research prototype, Project Mariner operates as an
agent within the Chrome browser (see Fig. 1). Its purpose is to understand a user's
intent and autonomously carry out web-based tasks on their behalf. For example, a
user could ask it to find three apartments for rent within a specific budget and
neighborhood; Mariner would then navigate to real estate websites, apply the filters,
browse the listings, and extract the relevant information into a document. This project
represents Google's exploration into creating a truly helpful and "agentive" web
experience where the browser actively works for the user.




              Fig.1: Interaction between and Agent and the Web Browser




                                                                                         2

Anthropic's Computer Use: This feature empowers Anthropic's AI model, Claude, to
become a direct user of a computer's desktop environment. By capturing screenshots
to perceive the screen and programmatically controlling the mouse and keyboard,
Claude can orchestrate workflows that span multiple, unconnected applications. A
user could ask it to analyze data in a PDF report, open a spreadsheet application to
perform calculations on that data, generate a chart, and then paste that chart into an
email draft—a sequence of tasks that previously required constant human input.

Browser Use: This is an open-source library that provides a high-level API for
programmatic browser automation. It enables AI agents to interface with web pages
by granting them access to and control over the Document Object Model (DOM). The
API abstracts the intricate, low-level commands of browser control protocols, into a
more simplified and intuitive set of functions. This allows an agent to perform complex
sequences of actions, including data extraction from nested elements, form
submissions, and automated navigation across multiple pages. As a result, the library
facilitates the transformation of unstructured web data into a structured format that
an AI agent can systematically process and utilize for analysis or decision-making.


Interaction: Agents with the Environment
Beyond the confines of a computer screen, AI agents are increasingly designed to
interact with complex, dynamic environments, often mirroring the real world. This
requires sophisticated perception, reasoning, and actuation capabilities.

Google's Project Astra is a prime example of an initiative pushing the boundaries of
agent interaction with the environment. Astra aims to create a universal AI agent that
is helpful in everyday life, leveraging multimodal inputs (sight, sound, voice) and
outputs to understand and interact with the world contextually. This project focuses
on rapid understanding, reasoning, and response, allowing the agent to "see" and
"hear" its surroundings through cameras and microphones and engage in natural
conversation while providing real-time assistance. Astra's vision is an agent that can
seamlessly assist users with tasks ranging from finding lost items to debugging code,
by understanding the environment it observes. This moves beyond simple voice
commands to a truly embodied understanding of the user's immediate physical
context.

Google's Gemini Live, transforms standard AI interactions into a fluid and dynamic
conversation. Users can speak to the AI and receive responses in a natural-sounding
voice with minimal delay, and can even interrupt or change topics mid-sentence,
prompting the AI to adapt immediately. The interface expands beyond voice, allowing

                                                                                         3

users to incorporate visual information by using their phone's camera, sharing their
screen, or uploading files for a more context-aware discussion. More advanced
versions can even perceive a user's tone of voice and intelligently filter out irrelevant
background noise to better understand the conversation. These capabilities combine
to create rich interactions, such as receiving live instructions on a task by simply
pointing a camera at it.

OpenAI's GPT-4o model is an alternative designed for "omni" interaction, meaning it
can reason across voice, vision, and text. It processes these inputs with low latency
that mirrors human response times, which allows for real-time conversations. For
example, users can show the AI a live video feed to ask questions about what is
happening, or use it for language translation. OpenAI provides developers with a
"Realtime API" to build applications requiring low-latency, speech-to-speech
interactions.

OpenAI's ChatGPT Agent represents a significant architectural advancement over its
predecessors, featuring an integrated framework of new capabilities. Its design
incorporates several key functional modalities: the capacity for autonomous
navigation of the live internet for real-time data extraction, the ability to dynamically
generate and execute computational code for tasks like data analysis, and the
functionality to interface directly with third-party software applications. The synthesis
of these functions allows the agent to orchestrate and complete complex, sequential
workflows from a singular user directive. It can therefore autonomously manage entire
processes, such as performing market analysis and generating a corresponding
presentation, or planning logistical arrangements and executing the necessary
transactions. In parallel with the launch, OpenAI has proactively addressed the
emergent safety considerations inherent in such a system. An accompanying "System
Card" delineates the potential operational hazards associated with an AI capable of
performing actions online, acknowledging the new vectors for misuse. To mitigate
these risks, the agent's architecture includes engineered safeguards, such as
requiring explicit user authorization for certain classes of actions and deploying
robust content filtering mechanisms. The company is now engaging its initial user
base to further refine these safety protocols through a feedback-driven, iterative
process.

Seeing AI, a complimentary mobile application from Microsoft, empowers individuals
who are blind or have low vision by offering real-time narration of their surroundings.
The app leverages artificial intelligence through the device's camera to identify and
describe various elements, including objects, text, and even people. Its core
functionalities encompass reading documents, recognizing currency, identifying
                                                                                            4

products through barcodes, and describing scenes and colors. By providing enhanced
access to visual information, Seeing AI ultimately fosters greater independence for
visually impaired users.

Anthropic's Claude 4 Series Anthropic's Claude 4 is another alternative with
capabilities for advanced reasoning and analysis. Though historically focused on text,
Claude 4 includes robust vision capabilities, allowing it to process information from
images, charts, and documents. The model is suited for handling complex, multi-step
tasks and providing detailed analysis. While the real-time conversational aspect is not
its primary focus compared to other models, its underlying intelligence is designed for
building highly capable AI agents.


Vibe Coding: Intuitive Development with AI
Beyond direct interaction with GUIs and the physical world, a new paradigm is
emerging in how developers build software with AI: "vibe coding." This approach
moves away from precise, step-by-step instructions and instead relies on a more
intuitive, conversational, and iterative interaction between the developer and an AI
coding assistant. The developer provides a high-level goal, a desired "vibe," or a
general direction, and the AI generates code to match.

This process is characterized by:

   -​ Conversational Prompts: Instead of writing detailed specifications, a
      developer might say, "Create a simple, modern-looking landing page for a new
      app," or, "Refactor this function to be more Pythonic and readable." The AI
      interprets the "vibe" of "modern" or "Pythonic" and generates the
      corresponding code.
   -​ Iterative Refinement: The initial output from the AI is often a starting point.
      The developer then provides feedback in natural language, such as, "That's a
      good start, but can you make the buttons blue?" or, "Add some error handling
      to that." This back-and-forth continues until the code meets the developer's
      expectations.
   -​ Creative Partnership: In vibe coding, the AI acts as a creative partner,
      suggesting ideas and solutions that the developer may not have considered.
      This can accelerate the development process and lead to more innovative
      outcomes.
   -​ Focus on "What" not "How": The developer focuses on the desired outcome
      (the "what") and leaves the implementation details (the "how") to the AI. This


                                                                                        5

      allows for rapid prototyping and exploration of different approaches without
      getting bogged down in boilerplate code.
   -​ Optional Memory Banks: To maintain context across longer interactions,
      developers can use "memory banks" to store key information, preferences, or
      constraints. For example, a developer might save a specific coding style or a
      set of project requirements to the AI's memory, ensuring that future code
      generations remain consistent with the established "vibe" without needing to
      repeat the instructions.

Vibe coding is becoming increasingly popular with the rise of powerful AI models like
GPT-4, Claude, and Gemini, which are integrated into development environments.
These tools are not just auto-completing code; they are actively participating in the
creative process of software development, making it more accessible and efficient.
This new way of working is changing the nature of software engineering, emphasizing
creativity and high-level thinking over rote memorization of syntax and APIs.


Key takeaways
   ●​ AI agents are evolving from simple automation to visually controlling software
      through graphical user interfaces, much like a human would.
   ●​ The next frontier is real-world interaction, with projects like Google's Astra
      using cameras and microphones to see, hear, and understand their physical
      surroundings.
   ●​ Leading technology companies are converging these digital and physical
      capabilities to create universal AI assistants that operate seamlessly across
      both domains.
   ●​ This shift is creating a new class of proactive, context-aware AI companions
      capable of assisting with a vast range of tasks in users' daily lives.

