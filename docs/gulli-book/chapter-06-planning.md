# Chapter 6: Planning

> From *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems* by Antonio Gulli.
> Source: [`docs/Agentic_Design_Patterns.pdf`](../Agentic_Design_Patterns.pdf) (extracted 2026-04-23 via `pdftotext -layout`).
> Overview: [`docs/gulli-book-overview.md`](../gulli-book-overview.md).
> Our platform's status on this pattern: see [`wiki/patterns/`](../../wiki/patterns/).

---

model to connect with external APIs for real-time data processing and action
execution. Extensions offer enterprise-grade security, data privacy, and performance
guarantees. They can be used for tasks like generating and running code, querying
websites, and analyzing information from private datastores. Google provides prebuilt
extensions for common use cases like Code Interpreter and Vertex AI Search, with the
option to create custom ones. The primary benefit of extensions includes strong

                                                                                   18

enterprise controls and seamless integration with other Google products. The key
difference between extensions and function calling lies in their execution: Vertex AI
automatically executes extensions, whereas function calls require manual execution
by the user or client.


At a Glance
What: LLMs are powerful text generators, but they are fundamentally disconnected
from the outside world. Their knowledge is static, limited to the data they were trained
on, and they lack the ability to perform actions or retrieve real-time information. This
inherent limitation prevents them from completing tasks that require interaction with
external APIs, databases, or services. Without a bridge to these external systems,
their utility for solving real-world problems is severely constrained.

Why: The Tool Use pattern, often implemented via function calling, provides a
standardized solution to this problem. It works by describing available external
functions, or "tools," to the LLM in a way it can understand. Based on a user's request,
the agentic LLM can then decide if a tool is needed and generate a structured data
object (like a JSON) specifying which function to call and with what arguments. An
orchestration layer executes this function call, retrieves the result, and feeds it back
to the LLM. This allows the LLM to incorporate up-to-date, external information or the
result of an action into its final response, effectively giving it the ability to act.

Rule of thumb: Use the Tool Use pattern whenever an agent needs to break out of
the LLM's internal knowledge and interact with the outside world. This is essential for
tasks requiring real-time data (e.g., checking weather, stock prices), accessing private
or proprietary information (e.g., querying a company's database), performing precise
calculations, executing code, or triggering actions in other systems (e.g., sending an
email, controlling smart devices).

Visual summary:




                                                                                        19

                          Fig.2: Tool use design pattern




Key Takeaways
 ●​ Tool Use (Function Calling) allows agents to interact with external systems and
    access dynamic information.
 ●​ It involves defining tools with clear descriptions and parameters that the LLM
    can understand.
 ●​ The LLM decides when to use a tool and generates structured function calls.
 ●​ Agentic frameworks execute the actual tool calls and return the results to the
    LLM.
 ●​ Tool Use is essential for building agents that can perform real-world actions
    and provide up-to-date information.
 ●​ LangChain simplifies tool definition using the @tool decorator and provides
    create_tool_calling_agent and AgentExecutor for building tool-using agents.

                                                                                  20

   ●​ Google ADK has a number of very useful pre-built tools such as Google Search,
      Code Execution and Vertex AI Search Tool.


Conclusion
The Tool Use pattern is a critical architectural principle for extending the functional
scope of large language models beyond their intrinsic text generation capabilities. By
equipping a model with the ability to interface with external software and data
sources, this paradigm allows an agent to perform actions, execute computations,
and retrieve information from other systems. This process involves the model
generating a structured request to call an external tool when it determines that doing
so is necessary to fulfill a user's query. Frameworks such as LangChain, Google ADK,
and Crew AI offer structured abstractions and components that facilitate the
integration of these external tools. These frameworks manage the process of
exposing tool specifications to the model and parsing its subsequent tool-use
requests. This simplifies the development of sophisticated agentic systems that can
interact with and take action within external digital environments.


References
   1.​ LangChain Documentation (Tools):
       https://python.langchain.com/docs/integrations/tools/
   2.​ Google Agent Developer Kit (ADK) Documentation (Tools):
       https://google.github.io/adk-docs/tools/
   3.​ OpenAI Function Calling Documentation:
       https://platform.openai.com/docs/guides/function-calling
   4.​ CrewAI Documentation (Tools): https://docs.crewai.com/concepts/tools




                                                                                     21

Chapter 6: Planning
Intelligent behavior often involves more than just reacting to the immediate input. It
requires foresight, breaking down complex tasks into smaller, manageable steps, and
strategizing how to achieve a desired outcome. This is where the Planning pattern
comes into play. At its core, planning is the ability for an agent or a system of agents
to formulate a sequence of actions to move from an initial state towards a goal state.


Planning Pattern Overview
In the context of AI, it's helpful to think of a planning agent as a specialist to whom
you delegate a complex goal. When you ask it to "organize a team offsite," you are
defining the what—the objective and its constraints—but not the how. The agent's
core task is to autonomously chart a course to that goal. It must first understand the
initial state (e.g., budget, number of participants, desired dates) and the goal state (a
successfully booked offsite), and then discover the optimal sequence of actions to
connect them. The plan is not known in advance; it is created in response to the
request.

A hallmark of this process is adaptability. An initial plan is merely a starting point, not a
rigid script. The agent's real power is its ability to incorporate new information and
steer the project around obstacles. For instance, if the preferred venue becomes
unavailable or a chosen caterer is fully booked, a capable agent doesn't simply fail. It
adapts. It registers the new constraint, re-evaluates its options, and formulates a new
plan, perhaps by suggesting alternative venues or dates.

However, it is crucial to recognize the trade-off between flexibility and predictability.
Dynamic planning is a specific tool, not a universal solution. When a problem's
solution is already well-understood and repeatable, constraining the agent to a
predetermined, fixed workflow is more effective. This approach limits the agent's
autonomy to reduce uncertainty and the risk of unpredictable behavior, guaranteeing
a reliable and consistent outcome. Therefore, the decision to use a planning agent
versus a simple task-execution agent hinges on a single question: does the "how"
need to be discovered, or is it already known?


Practical Applications & Use Cases
The Planning pattern is a core computational process in autonomous systems,
enabling an agent to synthesize a sequence of actions to achieve a specified goal,

                                                                                            1

particularly within dynamic or complex environments. This process transforms a
high-level objective into a structured plan composed of discrete, executable steps.

In domains such as procedural task automation, planning is used to orchestrate
complex workflows. For example, a business process like onboarding a new employee
can be decomposed into a directed sequence of sub-tasks, such as creating system
accounts, assigning training modules, and coordinating with different departments.
The agent generates a plan to execute these steps in a logical order, invoking
necessary tools or interacting with various systems to manage dependencies.

Within robotics and autonomous navigation, planning is fundamental for state-space
traversal. A system, whether a physical robot or a virtual entity, must generate a path
or sequence of actions to transition from an initial state to a goal state. This involves
optimizing for metrics such as time or energy consumption while adhering to
environmental constraints, like avoiding obstacles or following traffic regulations.

This pattern is also critical for structured information synthesis. When tasked with
generating a complex output like a research report, an agent can formulate a plan
that includes distinct phases for information gathering, data summarization, content
structuring, and iterative refinement. Similarly, in customer support scenarios involving
multi-step problem resolution, an agent can create and follow a systematic plan for
diagnosis, solution implementation, and escalation.

In essence, the Planning pattern allows an agent to move beyond simple, reactive
actions to goal-oriented behavior. It provides the logical framework necessary to solve
problems that require a coherent sequence of interdependent operations.


Hands-on code (Crew AI)
The following section will demonstrate an implementation of the Planner pattern using
the Crew AI framework. This pattern involves an agent that first formulates a
multi-step plan to address a complex query and then executes that plan sequentially.


 import os
 from dotenv import load_dotenv
 from crewai import Agent, Task, Crew, Process
 from langchain_openai import ChatOpenAI

 # Load environment variables from .env file for security
 load_dotenv()

                                                                                            2

# 1. Explicitly define the language model for clarity
llm = ChatOpenAI(model="gpt-4-turbo")

# 2. Define a clear and focused agent
planner_writer_agent = Agent(
   role='Article Planner and Writer',
   goal='Plan and then write a concise, engaging summary on a
specified topic.',
   backstory=(
       'You are an expert technical writer and content strategist. '
       'Your strength lies in creating a clear, actionable plan
before writing, '
       'ensuring the final summary is both informative and easy to
digest.'
   ),
   verbose=True,
   allow_delegation=False,
   llm=llm # Assign the specific LLM to the agent
)

# 3. Define a task with a more structured and specific expected
output
topic = "The importance of Reinforcement Learning in AI"
high_level_task = Task(
   description=(
       f"1. Create a bullet-point plan for a summary on the topic:
'{topic}'.\n"
       f"2. Write the summary based on your plan, keeping it around
200 words."
   ),
   expected_output=(
       "A final report containing two distinct sections:\n\n"
       "### Plan\n"
       "- A bulleted list outlining the main points of the
summary.\n\n"
       "### Summary\n"
       "- A concise and well-structured summary of the topic."
   ),
   agent=planner_writer_agent,
)

# Create the crew with a clear process
crew = Crew(
   agents=[planner_writer_agent],
   tasks=[high_level_task],
   process=Process.sequential,

                                                                       3

 )

 # Execute the task
 print("## Running the planning and writing task ##")
 result = crew.kickoff()

 print("\n\n---\n## Task Result ##\n---")
 print(result)


This code uses the CrewAI library to create an AI agent that plans and writes a
summary on a given topic. It starts by importing necessary libraries, including Crew.ai
and langchain_openai, and loading environment variables from a .env file. A
ChatOpenAI language model is explicitly defined for use with the agent. An Agent
named planner_writer_agent is created with a specific role and goal: to plan and then
write a concise summary. The agent's backstory emphasizes its expertise in planning
and technical writing. A Task is defined with a clear description to first create a plan and
then write a summary on the topic "The importance of Reinforcement Learning in AI",
with a specific format for the expected output. A Crew is assembled with the agent
and task, set to process them sequentially. Finally, the crew.kickoff() method is called to
execute the defined task and the result is printed.


Google DeepResearch
Google Gemini DeepResearch (see Fig.1) is an agent-based system designed for
autonomous information retrieval and synthesis. It functions through a multi-step
agentic pipeline that dynamically and iteratively queries Google Search to
systematically explore complex topics. The system is engineered to process a large
corpus of web-based sources, evaluate the collected data for relevance and
knowledge gaps, and perform subsequent searches to address them. The final output
consolidates the vetted information into a structured, multi-page summary with
citations to the original sources.

Expanding on this, the system's operation is not a single query-response event but a
managed, long-running process. It begins by deconstructing a user's prompt into a
multi-point research plan (see Fig. 1), which is then presented to the user for review
and modification. This allows for a collaborative shaping of the research trajectory
before execution. Once the plan is approved, the agentic pipeline initiates its iterative
search-and-analysis loop. This involves more than just executing a series of predefined
searches; the agent dynamically formulates and refines its queries based on the

                                                                                          4

information it gathers, actively identifying knowledge gaps, corroborating data points,
and resolving discrepancies.




  Fig. 1: Google Deep Research agent generating an execution plan for using Google
                                  Search as a tool.

A key architectural component is the system's ability to manage this process
asynchronously. This design ensures that the investigation, which can involve analyzing
hundreds of sources, is resilient to single-point failures and allows the user to
disengage and be notified upon completion. The system can also integrate

                                                                                          5

user-provided documents, combining information from private sources with its
web-based research. The final output is not merely a concatenated list of findings but a
structured, multi-page report. During the synthesis phase, the model performs a
critical evaluation of the collected information, identifying major themes and organizing
the content into a coherent narrative with logical sections. The report is designed to be
interactive, often including features like an audio overview, charts, and links to the
original cited sources, allowing for verification and further exploration by the user. In
addition to the synthesized results, the model explicitly returns the full list of sources it
searched and consulted (see Fig.2). These are presented as citations, providing
complete transparency and direct access to the primary information. This entire
process transforms a simple query into a comprehensive, synthesized body of
knowledge.




                                                                                           6

 Fig. 2: An example of Deep Research plan being executed, resulting in Google Search
                  being used as a tool to search various web sources.

By mitigating the substantial time and resource investment required for manual data
acquisition and synthesis, Gemini DeepResearch provides a more structured and
exhaustive method for information discovery. The system's value is particularly evident
in complex, multi-faceted research tasks across various domains.

For instance, in competitive analysis, the agent can be directed to systematically gather
and collate data on market trends, competitor product specifications, public sentiment
from diverse online sources, and marketing strategies. This automated process
replaces the laborious task of manually tracking multiple competitors, allowing analysts
to focus on higher-order strategic interpretation rather than data collection (see Fig. 3).




                                                                                         7

 Fig. 3: Final output generated by the Google Deep Research agent, analyzing on our
                 behalf sources obtained using Google Search as a tool.

Similarly, in academic exploration, the system serves as a powerful tool for conducting
extensive literature reviews. It can identify and summarize foundational papers, trace
the development of concepts across numerous publications, and map out emerging
research fronts within a specific field, thereby accelerating the initial and most
time-consuming phase of academic inquiry.

The efficiency of this approach stems from the automation of the iterative
search-and-filter cycle, which is a core bottleneck in manual research.
Comprehensiveness is achieved by the system's capacity to process a larger volume
and variety of information sources than is typically feasible for a human researcher
within a comparable timeframe. This broader scope of analysis helps to reduce the
potential for selection bias and increases the likelihood of uncovering less obvious but
potentially critical information, leading to a more robust and well-supported
understanding of the subject matter.


OpenAI Deep Research API
The OpenAI Deep Research API is a specialized tool designed to automate complex
research tasks. It utilizes an advanced, agentic model that can independently reason,
plan, and synthesize information from real-world sources. Unlike a simple Q&A model, it
takes a high-level query and autonomously breaks it down into sub-questions,
performs web searches using its built-in tools, and delivers a structured, citation-rich
final report. The API provides direct programmatic access to this entire process, using
at the time of writing models like o3-deep-research-2025-06-26 for high-quality
synthesis and the faster o4-mini-deep-research-2025-06-26 for latency-sensitive
application

The Deep Research API is useful because it automates what would otherwise be hours
of manual research, delivering professional-grade, data-driven reports suitable for
informing business strategy, investment decisions, or policy recommendations. Its key
benefits include:

   ●​ Structured, Cited Output: It produces well-organized reports with inline
      citations linked to source metadata, ensuring claims are verifiable and
      data-backed.


                                                                                           8

   ●​ Transparency: Unlike the abstracted process in ChatGPT, the API exposes all
      intermediate steps, including the agent's reasoning, the specific web search
      queries it executed, and any code it ran. This allows for detailed debugging,
      analysis, and a deeper understanding of how the final answer was constructed.
   ●​ Extensibility: It supports the Model Context Protocol (MCP), enabling
      developers to connect the agent to private knowledge bases and internal data
      sources, blending public web research with proprietary information.

To use the API, you send a request to the client.responses.create endpoint, specifying a
model, an input prompt, and the tools the agent can use. The input typically includes a
system_message that defines the agent's persona and desired output format, along
with the user_query. You must also include the web_search_preview tool and can
optionally add others like code_interpreter or custom MCP tools (see Chapter 10) for
internal data.


from openai import OpenAI

# Initialize the client with your API key
client = OpenAI(api_key="YOUR_OPENAI_API_KEY")

# Define the agent's role and the user's research question
system_message = """You are a professional researcher preparing a
structured, data-driven report.
Focus on data-rich insights, use reliable sources, and include inline
citations."""
user_query = "Research the economic impact of semaglutide on global
healthcare systems."

# Create the Deep Research API call
response = client.responses.create(
 model="o3-deep-research-2025-06-26",
 input=[
   {
     "role": "developer",
     "content": [{"type": "input_text", "text": system_message}]
   },
   {
     "role": "user",
     "content": [{"type": "input_text", "text": user_query}]
   }
 ],
 reasoning={"summary": "auto"},
 tools=[{"type": "web_search_preview"}]
)

                                                                                      9

# Access and print the final report from the response
final_report = response.output[-1].content[0].text
print(final_report)

# --- ACCESS INLINE CITATIONS AND METADATA ---
print("--- CITATIONS ---")
annotations = response.output[-1].content[0].annotations

if not annotations:
   print("No annotations found in the report.")
else:
   for i, citation in enumerate(annotations):
       # The text span the citation refers to
       cited_text =
final_report[citation.start_index:citation.end_index]

       print(f"Citation {i+1}:")
       print(f" Cited Text: {cited_text}")
       print(f" Title: {citation.title}")
       print(f" URL: {citation.url}")
       print(f" Location: chars
{citation.start_index}–{citation.end_index}")
print("\n" + "="*50 + "\n")

# --- INSPECT INTERMEDIATE STEPS ---
print("--- INTERMEDIATE STEPS ---")

# 1. Reasoning Steps: Internal plans and summaries generated by the
model.
try:
   reasoning_step = next(item for item in response.output if
item.type == "reasoning")
   print("\n[Found a Reasoning Step]")
   for summary_part in reasoning_step.summary:
       print(f" - {summary_part.text}")
except StopIteration:
   print("\nNo reasoning steps found.")

# 2. Web Search Calls: The exact search queries the agent executed.
try:
   search_step = next(item for item in response.output if item.type
== "web_search_call")
   print("\n[Found a Web Search Call]")
   print(f" Query Executed: '{search_step.action['query']}'")
   print(f" Status: {search_step.status}")
except StopIteration:

