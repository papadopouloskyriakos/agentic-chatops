# Appendix E: AI Agents on the CLI

> From *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems* by Antonio Gulli.
> Source: [`docs/Agentic_Design_Patterns.pdf`](../Agentic_Design_Patterns.pdf) (extracted 2026-04-23 via `pdftotext -layout`).
> Overview: [`docs/gulli-book-overview.md`](../gulli-book-overview.md).
> Our platform's status on this pattern: see [`wiki/patterns/`](../../wiki/patterns/).

---

   poem: str
   combined_output: str

# Nodes
def call_llm_1(state: State):
   """First LLM call to generate initial joke"""

    msg = llm.invoke(f"Write a joke about {state['topic']}")
    return {"joke": msg.content}




                                                                                            2

def call_llm_2(state: State):
   """Second LLM call to generate story"""

  msg = llm.invoke(f"Write a story about {state['topic']}")
  return {"story": msg.content}

def call_llm_3(state: State):
   """Third LLM call to generate poem"""

  msg = llm.invoke(f"Write a poem about {state['topic']}")
  return {"poem": msg.content}

def aggregator(state: State):
   """Combine the joke and story into a single output"""

   combined = f"Here's a story, joke, and poem about
{state['topic']}!\n\n"
   combined += f"STORY:\n{state['story']}\n\n"
   combined += f"JOKE:\n{state['joke']}\n\n"
   combined += f"POEM:\n{state['poem']}"
   return {"combined_output": combined}

# Build workflow
parallel_builder = StateGraph(State)

# Add nodes
parallel_builder.add_node("call_llm_1", call_llm_1)
parallel_builder.add_node("call_llm_2", call_llm_2)
parallel_builder.add_node("call_llm_3", call_llm_3)
parallel_builder.add_node("aggregator", aggregator)

# Add edges to connect nodes
parallel_builder.add_edge(START, "call_llm_1")
parallel_builder.add_edge(START, "call_llm_2")
parallel_builder.add_edge(START, "call_llm_3")
parallel_builder.add_edge("call_llm_1", "aggregator")
parallel_builder.add_edge("call_llm_2", "aggregator")
parallel_builder.add_edge("call_llm_3", "aggregator")
parallel_builder.add_edge("aggregator", END)
parallel_workflow = parallel_builder.compile()

# Show workflow
display(Image(parallel_workflow.get_graph().draw_mermaid_png()))

# Invoke
state = parallel_workflow.invoke({"topic": "cats"})
print(state["combined_output"])




                                                                   3

This code defines and runs a LangGraph workflow that operates in parallel. Its main
purpose is to simultaneously generate a joke, a story, and a poem about a given topic
and then combine them into a single, formatted text output.

Google's ADK
Google's Agent Development Kit, or ADK, provides a high-level, structured framework
for building and deploying applications composed of multiple, interacting AI agents. It
contrasts with LangChain and LangGraph by offering a more opinionated and
production-oriented system for orchestrating agent collaboration, rather than providing
the fundamental building blocks for an agent's internal logic.

LangChain operates at the most foundational level, offering the components and
standardized interfaces to create sequences of operations, such as calling a model and
parsing its output. LangGraph extends this by introducing a more flexible and powerful
control flow; it treats an agent's workflow as a stateful graph. Using LangGraph, a
developer explicitly defines nodes, which are functions or tools, and edges, which
dictate the path of execution. This graph structure allows for complex, cyclical reasoning
where the system can loop, retry tasks, and make decisions based on an explicitly
managed state object that is passed between nodes. It gives the developer fine-grained
control over a single agent's thought process or the ability to construct a multi-agent
system from first principles.

Google's ADK abstracts away much of this low-level graph construction. Instead of
asking the developer to define every node and edge, it provides pre-built architectural
patterns for multi-agent interaction. For instance, ADK has built-in agent types like
SequentialAgent or ParallelAgent, which manage the flow of control between different
agents automatically. It is architected around the concept of a "team" of agents, often
with a primary agent delegating tasks to specialized sub-agents. State and session
management are handled more implicitly by the framework, providing a more cohesive
but less granular approach than LangGraph's explicit state passing. Therefore, while
LangGraph gives you the detailed tools to design the intricate wiring of a single robot or
a team, Google's ADK gives you a factory assembly line designed to build and manage
a fleet of robots that already know how to work together.

Python

 from google.adk.agents import LlmAgent
 from google.adk.tools import google_Search

 dice_agent = LlmAgent(



                                                                                          4

    model="gemini-2.0-flash-exp",
    name="question_answer_agent",
    description="A helpful assistant agent that can answer
 questions.",
    instruction="""Respond to the query using google search""",
    tools=[google_search],
 )


This code creates a search-augmented agent. When this agent receives a question, it
will not just rely on its pre-existing knowledge. Instead, following its instructions, it will
use the Google Search tool to find relevant, real-time information from the web and then
use that information to construct its answer.

Crew.AI
CrewAI offers an orchestration framework for building multi-agent systems by focusing
on collaborative roles and structured processes. It operates at a higher level of
abstraction than foundational toolkits, providing a conceptual model that mirrors a
human team. Instead of defining the granular flow of logic as a graph, the developer
defines the actors and their assignments, and CrewAI manages their interaction.

The core components of this framework are Agents, Tasks, and the Crew. An Agent is
defined not just by its function but by a persona, including a specific role, a goal, and a
backstory, which guides its behavior and communication style. A Task is a discrete unit
of work with a clear description and expected output, assigned to a specific Agent. The
Crew is the cohesive unit that contains the Agents and the list of Tasks, and it executes
a predefined Process. This process dictates the workflow, which is typically either
sequential, where the output of one task becomes the input for the next in line, or
hierarchical, where a manager-like agent delegates tasks and coordinates the workflow
among other agents.

When compared to other frameworks, CrewAI occupies a distinct position. It moves
away from the low-level, explicit state management and control flow of LangGraph,
where a developer wires together every node and conditional edge. Instead of building
a state machine, the developer designs a team charter. While Googlés ADK provides a
comprehensive, production-oriented platform for the entire agent lifecycle, CrewAI
concentrates specifically on the logic of agent collaboration and for simulating a team of
specialists

Python




                                                                                             5

 @crew
 def crew(self) -> Crew:
    """Creates the research crew"""
    return Crew(
      agents=self.agents,
      tasks=self.tasks,
      process=Process.sequential,
      verbose=True,
    )


This code sets up a sequential workflow for a team of AI agents, where they tackle a list
of tasks in a specific order, with detailed logging enabled to monitor their progress.

Other agent development framework
Microsoft AutoGen: AutoGen is a framework centered on orchestrating multiple agents
that solve tasks through conversation. Its architecture enables agents with distinct
capabilities to interact, allowing for complex problem decomposition and collaborative
resolution. The primary advantage of AutoGen is its flexible, conversation-driven
approach that supports dynamic and complex multi-agent interactions. However, this
conversational paradigm can lead to less predictable execution paths and may require
sophisticated prompt engineering to ensure tasks converge efficiently.

LlamaIndex: LlamaIndex is fundamentally a data framework designed to connect large
language models with external and private data sources. It excels at creating
sophisticated data ingestion and retrieval pipelines, which are essential for building
knowledgeable agents that can perform RAG. While its data indexing and querying
capabilities are exceptionally powerful for creating context-aware agents, its native tools
for complex agentic control flow and multi-agent orchestration are less developed
compared to agent-first frameworks. LlamaIndex is optimal when the core technical
challenge is data retrieval and synthesis.

