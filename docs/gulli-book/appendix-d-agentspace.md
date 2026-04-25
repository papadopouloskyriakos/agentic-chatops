# Appendix D: Building an Agent with AgentSpace

> From *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems* by Antonio Gulli.
> Source: [`docs/Agentic_Design_Patterns.pdf`](../Agentic_Design_Patterns.pdf) (extracted 2026-04-23 via `pdftotext -layout`).
> Overview: [`docs/gulli-book-overview.md`](../gulli-book-overview.md).
> Our platform's status on this pattern: see [`wiki/patterns/`](../../wiki/patterns/).

---


Conclusion
Agents are undergoing a significant transformation, moving from basic automation to
sophisticated interaction with both digital and physical environments. By leveraging
visual perception to operate Graphical User Interfaces, these agents can now
manipulate software just as a human would, bypassing the need for traditional APIs.
Major technology labs are pioneering this space with agents capable of automating
complex, multi-application workflows directly on a user's desktop. Simultaneously, the
next frontier is expanding into the physical world, with initiatives like Google's Project
Astra using cameras and microphones to contextually engage with their surroundings.

                                                                                         6

These advanced systems are designed for multimodal, real-time understanding that
mirrors human interaction.

The ultimate vision is a convergence of these digital and physical capabilities, creating
universal AI assistants that operate seamlessly across all of a user's environments.
This evolution is also reshaping software creation itself through "vibe coding," a more
intuitive and conversational partnership between developers and AI. This new method
prioritizes high-level goals and creative intent, allowing developers to focus on the
desired outcome rather than implementation details. This shift accelerates
development and fosters innovation by treating AI as a creative partner. Ultimately,
these advancements are paving the way for a new era of proactive, context-aware AI
companions capable of assisting with a vast array of tasks in our daily lives.


References
   1.​ Open AI Operator, https://openai.com/index/introducing-operator/
   2.​ Open AI ChatGPT Agent: https://openai.com/index/introducing-chatgpt-agent/
   3.​ Browser Use: https://docs.browser-use.com/introduction
   4.​ Project Mariner, https://deepmind.google/models/project-mariner/
   5.​ Anthropic Computer use:
       https://docs.anthropic.com/en/docs/build-with-claude/computer-use
   6.​ Project Astra, https://deepmind.google/models/project-astra/
   7.​ Gemini Live, https://gemini.google/overview/gemini-live/?hl=en
   8.​ OpenAI's GPT-4, https://openai.com/index/gpt-4-research/
   9.​ Claude 4, https://www.anthropic.com/news/claude-4




                                                                                        7

Appendix C - Quick overview of Agentic
Frameworks
LangChain
LangChain is a framework for developing applications powered by LLMs. Its core
strength lies in its LangChain Expression Language (LCEL), which allows you to "pipe"
components together into a chain. This creates a clear, linear sequence where the
output of one step becomes the input for the next. It's built for workflows that are
Directed Acyclic Graphs (DAGs), meaning the process flows in one direction without
loops.

Use it for:

   ●​ Simple RAG: Retrieve a document, create a prompt, get an answer from an LLM.
   ●​ Summarization: Take user text, feed it to a summarization prompt, and return the
      output.
   ●​ Extraction: Extract structured data (like JSON) from a block of text.

Python

 # A simple LCEL chain conceptually
 # (This is not runnable code, just illustrates the flow)
 chain = prompt | model | output_parse


LangGraph
LangGraph is a library built on top of LangChain to handle more advanced agentic
systems. It allows you to define your workflow as a graph with nodes (functions or LCEL
chains) and edges (conditional logic). Its main advantage is the ability to create cycles,
allowing the application to loop, retry, or call tools in a flexible order until a task is
complete. It explicitly manages the application state, which is passed between nodes
and updated throughout the process.

Use it for:

   ●​ Multi-agent Systems: A supervisor agent routes tasks to specialized worker
      agents, potentially looping until the goal is met.


                                                                                         1

  ●​ Plan-and-Execute Agents: An agent creates a plan, executes a step, and then
     loops back to update the plan based on the result.
  ●​ Human-in-the-Loop: The graph can wait for human input before deciding which
     node to go to next.

Feature             LangChain                        LangGraph

Core Abstraction    Chain (using LCEL)               Graph of Nodes

Workflow Type       Linear (Directed Acyclic         Cyclical (Graphs with loops)
                    Graph)

State               Generally stateless per run      Explicit and persistent state
Management                                           object

Primary Use         Simple, predictable              Complex, dynamic, stateful
                    sequences                        agents

Which One Should You Use?

  ●​ Choose LangChain when your application has a clear, predictable, and linear
     flow of steps. If you can define the process from A to B to C without needing to
     loop back, LangChain with LCEL is the perfect tool.
  ●​ Choose LangGraph when you need your application to reason, plan, or operate
     in a loop. If your agent needs to use tools, reflect on the results, and potentially
     try again with a different approach, you need the cyclical and stateful nature of
     LangGraph.

Python

# Graph state
class State(TypedDict):
   topic: str
   joke: str
   story: str
