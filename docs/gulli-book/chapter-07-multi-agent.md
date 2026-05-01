# Chapter 7: Multi-Agent Collaboration

> From *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems* by Antonio Gulli.
> Source: [`docs/Agentic_Design_Patterns.pdf`](../Agentic_Design_Patterns.pdf) (extracted 2026-04-23 via `pdftotext -layout`).
> Overview: [`docs/gulli-book-overview.md`](../gulli-book-overview.md).
> Our platform's status on this pattern: see [`wiki/patterns/`](../../wiki/patterns/).

---

                                                                      10

    print("\nNo web search steps found.")

 # 3. Code Execution: Any code run by the agent using the code
 interpreter.
 try:
    code_step = next(item for item in response.output if item.type ==
 "code_interpreter_call")
    print("\n[Found a Code Execution Step]")
    print(" Code Input:")
    print(f" ```python\n{code_step.input}\n ```")
    print(" Code Output:")
    print(f" {code_step.output}")
 except StopIteration:
    print("\nNo code execution steps found.")


This code snippet utilizes the OpenAI API to perform a "Deep Research" task. It starts
by initializing the OpenAI client with your API key, which is crucial for authentication.
Then, it defines the role of the AI agent as a professional researcher and sets the user's
research question about the economic impact of semaglutide. The code constructs an
API call to the o3-deep-research-2025-06-26 model, providing the defined system
message and user query as input. It also requests an automatic summary of the
reasoning and enables web search capabilities. After making the API call, it extracts and
prints the final generated report.

Subsequently, it attempts to access and display inline citations and metadata from the
report's annotations, including the cited text, title, URL, and location within the report.
Finally, it inspects and prints details about the intermediate steps the model took, such
as reasoning steps, web search calls (including the query executed), and any code
execution steps if a code interpreter was used.


At a Glance
What: Complex problems often cannot be solved with a single action and require
foresight to achieve a desired outcome. Without a structured approach, an agentic
system struggles to handle multifaceted requests that involve multiple steps and
dependencies. This makes it difficult to break down high-level objectives into a
manageable series of smaller, executable tasks. Consequently, the system fails to
strategize effectively, leading to incomplete or incorrect results when faced with
intricate goals.



                                                                                          11

Why: The Planning pattern offers a standardized solution by having an agentic system
first create a coherent plan to address a goal. It involves decomposing a high-level
objective into a sequence of smaller, actionable steps or sub-goals. This allows the
system to manage complex workflows, orchestrate various tools, and handle
dependencies in a logical order. LLMs are particularly well-suited for this, as they can
generate plausible and effective plans based on their vast training data. This structured
approach transforms a simple reactive agent into a strategic executor that can
proactively work towards a complex objective and even adapt its plan if necessary.

Rule of thumb: Use this pattern when a user's request is too complex to be handled by
a single action or tool. It is ideal for automating multi-step processes, such as
generating a detailed research report, onboarding a new employee, or executing a
competitive analysis. Apply the Planning pattern whenever a task requires a sequence
of interdependent operations to reach a final, synthesized outcome.

Visual summary




                             Fig.4; Planning design pattern



                                                                                       12

Key Takeaways
●​ Planning enables agents to break down complex goals into actionable, sequential
   steps.
●​ It is essential for handling multi-step tasks, workflow automation, and navigating
   complex environments.
●​ LLMs can perform planning by generating step-by-step approaches based on
   task descriptions.
●​ Explicitly prompting or designing tasks to require planning steps encourages this
   behavior in agent frameworks.
●​ Google Deep Research is an agent analyzing on our behalf sources obtained using
   Google Search as a tool. It reflects, plans, and executes


Conclusion
In conclusion, the Planning pattern is a foundational component that elevates agentic
systems from simple reactive responders to strategic, goal-oriented executors.
Modern large language models provide the core capability for this, autonomously
decomposing high-level objectives into coherent, actionable steps. This pattern
scales from straightforward, sequential task execution, as demonstrated by the
CrewAI agent creating and following a writing plan, to more complex and dynamic
systems. The Google DeepResearch agent exemplifies this advanced application,
creating iterative research plans that adapt and evolve based on continuous
information gathering. Ultimately, planning provides the essential bridge between
human intent and automated execution for complex problems. By structuring a
problem-solving approach, this pattern enables agents to manage intricate workflows
and deliver comprehensive, synthesized results.


References
   1.​ Google DeepResearch (Gemini Feature): gemini.google.com
   2.​ OpenAI ,Introducing deep research https://openai.com/index/introducing-deep-research/
   3.​ Perplexity, Introducing Perplexity Deep Research,
       https://www.perplexity.ai/hub/blog/introducing-perplexity-deep-research




                                                                                         13

Chapter 7: Multi-Agent Collaboration
While a monolithic agent architecture can be effective for well-defined problems, its
capabilities are often constrained when faced with complex, multi-domain tasks. The
Multi-Agent Collaboration pattern addresses these limitations by structuring a system
as a cooperative ensemble of distinct, specialized agents. This approach is predicated
on the principle of task decomposition, where a high-level objective is broken down
into discrete sub-problems. Each sub-problem is then assigned to an agent
possessing the specific tools, data access, or reasoning capabilities best suited for
that task.

For example, a complex research query might be decomposed and assigned to a
Research Agent for information retrieval, a Data Analysis Agent for statistical
processing, and a Synthesis Agent for generating the final report. The efficacy of such
a system is not merely due to the division of labor but is critically dependent on the
mechanisms for inter-agent communication. This requires a standardized
communication protocol and a shared ontology, allowing agents to exchange data,
delegate sub-tasks, and coordinate their actions to ensure the final output is
coherent.

This distributed architecture offers several advantages, including enhanced
modularity, scalability, and robustness, as the failure of a single agent does not
necessarily cause a total system failure. The collaboration allows for a synergistic
outcome where the collective performance of the multi-agent system surpasses the
potential capabilities of any single agent within the ensemble.


Multi-Agent Collaboration Pattern Overview
The Multi-Agent Collaboration pattern involves designing systems where multiple
independent or semi-independent agents work together to achieve a common goal.
Each agent typically has a defined role, specific goals aligned with the overall
objective, and potentially access to different tools or knowledge bases. The power of
this pattern lies in the interaction and synergy between these agents.

Collaboration can take various forms:
●​ Sequential Handoffs: One agent completes a task and passes its output to
    another agent for the next step in a pipeline (similar to the Planning pattern, but
    explicitly involving different agents).


                                                                                          1

●​ Parallel Processing: Multiple agents work on different parts of a problem
   simultaneously, and their results are later combined.
●​ Debate and Consensus: Multi-Agent Collaboration where Agents with varied
   perspectives and information sources engage in discussions to evaluate options,
   ultimately reaching a consensus or a more informed decision.
●​ Hierarchical Structures: A manager agent might delegate tasks to worker
   agents dynamically based on their tool access or plugin capabilities and
   synthesize their results. Each agent can also handle relevant groups of tools,
   rather than a single agent handling all the tools.
●​ Expert Teams: Agents with specialized knowledge in different domains (e.g., a
   researcher, a writer, an editor) collaborate to produce a complex output.
●​ Critic-Reviewer: Agents create initial outputs such as plans, drafts, or answers. A
   second group of agents then critically assesses this output for adherence to
   policies, security, compliance, correctness, quality, and alignment with
   organizational objectives. The original creator or a final agent revises the output
   based on this feedback. This pattern is particularly effective for code generation,
   research writing, logic checking, and ensuring ethical alignment. The advantages
   of this approach include increased robustness, improved quality, and a reduced
   likelihood of hallucinations or errors.
A multi-agent system (see Fig.1) fundamentally comprises the delineation of agent
roles and responsibilities, the establishment of communication channels through
which agents exchange information, and the formulation of a task flow or interaction
protocol that directs their collaborative endeavors.




                                                                                       2

                        Fig.1: Example of multi-agent system

Frameworks such as Crew AI and Google ADK are engineered to facilitate this
paradigm by providing structures for the specification of agents, tasks, and their
interactive procedures. This approach is particularly effective for challenges
necessitating a variety of specialized knowledge, encompassing multiple discrete
phases, or leveraging the advantages of concurrent processing and the corroboration
of information across agents.


Practical Applications & Use Cases
Multi-Agent Collaboration is a powerful pattern applicable across numerous domains:
●​ Complex Research and Analysis: A team of agents could collaborate on a
   research project. One agent might specialize in searching academic databases,
   another in summarizing findings, a third in identifying trends, and a fourth in
   synthesizing the information into a report. This mirrors how a human research
   team might operate.
●​ Software Development: Imagine agents collaborating on building software. One
   agent could be a requirements analyst, another a code generator, a third a tester,



                                                                                    3

   and a fourth a documentation writer. They could pass outputs between each
   other to build and verify components.
●​ Creative Content Generation: Creating a marketing campaign could involve a
   market research agent, a copywriter agent, a graphic design agent (using image
   generation tools), and a social media scheduling agent, all working together.
●​ Financial Analysis: A multi-agent system could analyze financial markets. Agents
   might specialize in fetching stock data, analyzing news sentiment, performing
   technical analysis, and generating investment recommendations.
●​ Customer Support Escalation: A front-line support agent could handle initial
   queries, escalating complex issues to a specialist agent (e.g., a technical expert
   or a billing specialist) when needed, demonstrating a sequential handoff based on
   problem complexity.
●​ Supply Chain Optimization: Agents could represent different nodes in a supply
   chain (suppliers, manufacturers, distributors) and collaborate to optimize
   inventory levels, logistics, and scheduling in response to changing demand or
   disruptions.
●​ Network Analysis & Remediation: Autonomous operations benefit greatly from
   an agentic architecture, particularly in failure pinpointing. Multiple agents can
   collaborate to triage and remediate issues, suggesting optimal actions. These
   agents can also integrate with traditional machine learning models and tooling,
   leveraging existing systems while simultaneously offering the advantages of
   Generative AI.
The capacity to delineate specialized agents and meticulously orchestrate their
interrelationships empowers developers to construct systems exhibiting enhanced
modularity, scalability, and the ability to address complexities that would prove
insurmountable for a singular, integrated agent.


Multi-Agent Collaboration: Exploring
Interrelationships and Communication Structures
Understanding the intricate ways in which agents interact and communicate is
fundamental to designing effective multi-agent systems. As depicted in Fig. 2, a
spectrum of interrelationship and communication models exists, ranging from the
simplest single-agent scenario to complex, custom-designed collaborative
frameworks. Each model presents unique advantages and challenges, influencing the
overall efficiency, robustness, and adaptability of the multi-agent system.



                                                                                    4

1. Single Agent: At the most basic level, a "Single Agent" operates autonomously
without direct interaction or communication with other entities. While this model is
straightforward to implement and manage, its capabilities are inherently limited by the
individual agent's scope and resources. It is suitable for tasks that are decomposable
into independent sub-problems, each solvable by a single, self-sufficient agent.

2. Network: The "Network" model represents a significant step towards collaboration,
where multiple agents interact directly with each other in a decentralized fashion.
Communication typically occurs peer-to-peer, allowing for the sharing of information,
resources, and even tasks. This model fosters resilience, as the failure of one agent
does not necessarily cripple the entire system. However, managing communication
overhead and ensuring coherent decision-making in a large, unstructured network
can be challenging.

3. Supervisor: In the "Supervisor" model, a dedicated agent, the "supervisor,"
oversees and coordinates the activities of a group of subordinate agents. The
supervisor acts as a central hub for communication, task allocation, and conflict
resolution. This hierarchical structure offers clear lines of authority and can simplify
management and control. However, it introduces a single point of failure (the
supervisor) and can become a bottleneck if the supervisor is overwhelmed by a large
number of subordinates or complex tasks.

4. Supervisor as a Tool: This model is a nuanced extension of the "Supervisor"
concept, where the supervisor's role is less about direct command and control and
more about providing resources, guidance, or analytical support to other agents. The
supervisor might offer tools, data, or computational services that enable other agents
to perform their tasks more effectively, without necessarily dictating their every
action. This approach aims to leverage the supervisor's capabilities without imposing
rigid top-down control.

5. Hierarchical: The "Hierarchical" model expands upon the supervisor concept to
create a multi-layered organizational structure. This involves multiple levels of
supervisors, with higher-level supervisors overseeing lower-level ones, and ultimately,
a collection of operational agents at the lowest tier. This structure is well-suited for
complex problems that can be decomposed into sub-problems, each managed by a
specific layer of the hierarchy. It provides a structured approach to scalability and
complexity management, allowing for distributed decision-making within defined
boundaries.



                                                                                           5

               Fig. 2: Agents communicate and interact in various ways.

6. Custom: The "Custom" model represents the ultimate flexibility in multi-agent
system design. It allows for the creation of unique interrelationship and
communication structures tailored precisely to the specific requirements of a given
problem or application. This can involve hybrid approaches that combine elements
from the previously mentioned models, or entirely novel designs that emerge from the
unique constraints and opportunities of the environment. Custom models often arise
from the need to optimize for specific performance metrics, handle highly dynamic
environments, or incorporate domain-specific knowledge into the system's
architecture. Designing and implementing custom models typically requires a deep
understanding of multi-agent systems principles and careful consideration of
communication protocols, coordination mechanisms, and emergent behaviors.

In summary, the choice of interrelationship and communication model for a
multi-agent system is a critical design decision. Each model offers distinct advantages
and disadvantages, and the optimal choice depends on factors such as the
complexity of the task, the number of agents, the desired level of autonomy, the need

                                                                                      6

for robustness, and the acceptable communication overhead. Future advancements in
multi-agent systems will likely continue to explore and refine these models, as well as
develop new paradigms for collaborative intelligence.


Hands-On code (Crew AI)
This Python code defines an AI-powered crew using the CrewAI framework to
generate a blog post about AI trends. It starts by setting up the environment, loading
API keys from a .env file. The core of the application involves defining two agents: a
researcher to find and summarize AI trends, and a writer to create a blog post based
on the research.

Two tasks are defined accordingly: one for researching the trends and another for
writing the blog post, with the writing task depending on the output of the research
task. These agents and tasks are then assembled into a Crew, specifying a sequential
process where tasks are executed in order. The Crew is initialized with the agents,
tasks, and a language model (specifically the "gemini-2.0-flash" model). The main
function executes this crew using the kickoff() method, orchestrating the
collaboration between the agents to produce the desired output. Finally, the code
prints the final result of the crew's execution, which is the generated blog post.


import os
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process
from langchain_google_genai import ChatGoogleGenerativeAI

def setup_environment():
   """Loads environment variables and checks for the required API
key."""
   load_dotenv()
   if not os.getenv("GOOGLE_API_KEY"):
       raise ValueError("GOOGLE_API_KEY not found. Please set it in
your .env file.")

def main():
   """
   Initializes and runs the AI crew for content creation using the
latest Gemini model.
   """
   setup_environment()

    # Define the language model to use.


                                                                                         7

   # Updated to a model from the Gemini 2.0 series for better
performance and features.
   # For cutting-edge (preview) capabilities, you could use
"gemini-2.5-flash".
   llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")

   # Define Agents with specific roles and goals
   researcher = Agent(
       role='Senior Research Analyst',
       goal='Find and summarize the latest trends in AI.',
       backstory="You are an experienced research analyst with a
knack for identifying key trends and synthesizing information.",
       verbose=True,
       allow_delegation=False,
   )

   writer = Agent(
       role='Technical Content Writer',
       goal='Write a clear and engaging blog post based on research
findings.',
       backstory="You are a skilled writer who can translate complex
technical topics into accessible content.",
       verbose=True,
       allow_delegation=False,
   )

   # Define Tasks for the agents
   research_task = Task(
       description="Research the top 3 emerging trends in Artificial
Intelligence in 2024-2025. Focus on practical applications and
potential impact.",
       expected_output="A detailed summary of the top 3 AI trends,
including key points and sources.",
       agent=researcher,
   )

   writing_task = Task(
       description="Write a 500-word blog post based on the research
findings. The post should be engaging and easy for a general audience
to understand.",
       expected_output="A complete 500-word blog post about the
latest AI trends.",
       agent=writer,
       context=[research_task],
   )

  # Create the Crew

                                                                        8

    blog_creation_crew = Crew(
        agents=[researcher, writer],
        tasks=[research_task, writing_task],
        process=Process.sequential,
        llm=llm,
        verbose=2 # Set verbosity for detailed crew execution logs
    )

    # Execute the Crew
    print("## Running the blog creation crew with Gemini 2.0 Flash...
 ##")
    try:
        result = blog_creation_crew.kickoff()
        print("\n------------------\n")
        print("## Crew Final Output ##")
        print(result)
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")


 if __name__ == "__main__":
    main()
​
We will now delve into further examples within the Google ADK framework, with
particular emphasis on hierarchical, parallel, and sequential coordination paradigms,
alongside the implementation of an agent as an operational instrument.

Hands-on Code (Google ADK)
The following code example demonstrates the establishment of a hierarchical agent
structure within the Google ADK through the creation of a parent-child relationship.
The code defines two types of agents: LlmAgent and a custom TaskExecutor agent
derived from BaseAgent. The TaskExecutor is designed for specific, non-LLM tasks
and in this example, it simply yields a "Task finished successfully" event. An LlmAgent
named greeter is initialized with a specified model and instruction to act as a friendly
greeter. The custom TaskExecutor is instantiated as task_doer. A parent LlmAgent
called coordinator is created, also with a model and instructions. The coordinator's
instructions guide it to delegate greetings to the greeter and task execution to the
task_doer. The greeter and task_doer are added as sub-agents to the coordinator,
establishing a parent-child relationship. The code then asserts that this relationship is
correctly set up. Finally, it prints a message indicating that the agent hierarchy has
been successfully created.


                                                                                        9

from google.adk.agents import LlmAgent, BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from typing import AsyncGenerator

# Correctly implement a custom agent by extending BaseAgent
class TaskExecutor(BaseAgent):
   """A specialized agent with custom, non-LLM behavior."""
   name: str = "TaskExecutor"
   description: str = "Executes a predefined task."

   async def _run_async_impl(self, context: InvocationContext) ->
AsyncGenerator[Event, None]:
       """Custom implementation logic for the task."""
       # This is where your custom logic would go.
       # For this example, we'll just yield a simple event.
       yield Event(author=self.name, content="Task finished
successfully.")

# Define individual agents with proper initialization
# LlmAgent requires a model to be specified.
greeter = LlmAgent(
   name="Greeter",
   model="gemini-2.0-flash-exp",
   instruction="You are a friendly greeter."
)
task_doer = TaskExecutor() # Instantiate our concrete custom agent

# Create a parent agent and assign its sub-agents
# The parent agent's description and instructions should guide its
delegation logic.
coordinator = LlmAgent(
   name="Coordinator",
   model="gemini-2.0-flash-exp",
   description="A coordinator that can greet users and execute
tasks.",
   instruction="When asked to greet, delegate to the Greeter. When
asked to perform a task, delegate to the TaskExecutor.",
   sub_agents=[
       greeter,
       task_doer
   ]
)

# The ADK framework automatically establishes the parent-child

                                                                     10

relationships.
# These assertions will pass if checked after initialization.
assert greeter.parent_agent == coordinator
assert task_doer.parent_agent == coordinator

print("Agent hierarchy created successfully.")


This code excerpt illustrates the employment of the LoopAgent within the Google ADK
framework to establish iterative workflows. The code defines two agents:
ConditionChecker and ProcessingStep. ConditionChecker is a custom agent that
checks a "status" value in the session state. If the "status" is "completed",
ConditionChecker escalates an event to stop the loop. Otherwise, it yields an event to
continue the loop. ProcessingStep is an LlmAgent using the "gemini-2.0-flash-exp"
model. Its instruction is to perform a task and set the session "status" to "completed"
if it's the final step. A LoopAgent named StatusPoller is created. StatusPoller is
configured with max_iterations=10. StatusPoller includes both ProcessingStep and an
instance of ConditionChecker as sub-agents. The LoopAgent will execute the
sub-agents sequentially for up to 10 iterations, stopping if ConditionChecker finds the
status is "completed".



import asyncio
from typing import AsyncGenerator
from google.adk.agents import LoopAgent, LlmAgent, BaseAgent
from google.adk.events import Event, EventActions
from google.adk.agents.invocation_context import InvocationContext

# Best Practice: Define custom agents as complete, self-describing
classes.
class ConditionChecker(BaseAgent):
   """A custom agent that checks for a 'completed' status in the
session state."""
   name: str = "ConditionChecker"
   description: str = "Checks if a process is complete and signals
the loop to stop."

   async def _run_async_impl(
       self, context: InvocationContext
   ) -> AsyncGenerator[Event, None]:
       """Checks state and yields an event to either continue or stop
the loop."""
       status = context.session.state.get("status", "pending")


                                                                                     11

         is_done = (status == "completed")

         if is_done:
             # Escalate to terminate the loop when the condition is
met.
           yield Event(author=self.name,
actions=EventActions(escalate=True))
       else:
           # Yield a simple event to continue the loop.
           yield Event(author=self.name, content="Condition not met,
continuing loop.")

# Correction: The LlmAgent must have a model and clear instructions.
process_step = LlmAgent(
   name="ProcessingStep",
   model="gemini-2.0-flash-exp",
   instruction="You are a step in a longer process. Perform your
task. If you are the final step, update session state by setting
'status' to 'completed'."
)

# The LoopAgent orchestrates the workflow.
poller = LoopAgent(
   name="StatusPoller",
   max_iterations=10,
   sub_agents=[
       process_step,
       ConditionChecker() # Instantiating the well-defined custom
agent.
   ]
)

# This poller will now execute 'process_step'
# and then 'ConditionChecker'
# repeatedly until the status is 'completed' or 10 iterations
# have passed.


This code excerpt elucidates the SequentialAgent pattern within the Google ADK,
engineered for the construction of linear workflows. This code defines a sequential
agent pipeline using the google.adk.agents library. The pipeline consists of two
agents, step1 and step2. step1 is named "Step1_Fetch" and its output will be stored in
the session state under the key "data". step2 is named "Step2_Process" and is
instructed to analyze the information stored in session.state["data"] and provide a
summary. The SequentialAgent named "MyPipeline" orchestrates the execution of

                                                                                     12

these sub-agents. When the pipeline is run with an initial input, step1 will execute first.
The response from step1 will be saved into the session state under the key "data".
Subsequently, step2 will execute, utilizing the information that step1 placed into the
state as per its instruction. This structure allows for building workflows where the
output of one agent becomes the input for the next. This is a common pattern in
creating multi-step AI or data processing pipelines.



 from google.adk.agents import SequentialAgent, Agent

 # This agent's output will be saved to session.state["data"]
 step1 = Agent(name="Step1_Fetch", output_key="data")

 # This agent will use the data from the previous step.
 # We instruct it on how to find and use this data.
 step2 = Agent(
    name="Step2_Process",
    instruction="Analyze the information found in state['data'] and
 provide a summary."
 )

 pipeline = SequentialAgent(
    name="MyPipeline",
    sub_agents=[step1, step2]
 )

 # When the pipeline is run with an initial input, Step1 will execute,
 # its response will be stored in session.state["data"], and then
 # Step2 will execute, using the information from the state as
 instructed.


The following code example illustrates the ParallelAgent pattern within the Google
ADK, which facilitates the concurrent execution of multiple agent tasks. The
data_gatherer is designed to run two sub-agents concurrently: weather_fetcher and
news_fetcher. The weather_fetcher agent is instructed to get the weather for a given
location and store the result in session.state["weather_data"]. Similarly, the
news_fetcher agent is instructed to retrieve the top news story for a given topic and
store it in session.state["news_data"]. Each sub-agent is configured to use the
"gemini-2.0-flash-exp" model. The ParallelAgent orchestrates the execution of these
sub-agents, allowing them to work in parallel. The results from both weather_fetcher
and news_fetcher would be gathered and stored in the session state. Finally, the


                                                                                        13

example shows how to access the collected weather and news data from the
final_state after the agent's execution is complete.



from google.adk.agents import Agent, ParallelAgent

# It's better to define the fetching logic as tools for the agents
# For simplicity in this example, we'll embed the logic in the
agent's instruction.
# In a real-world scenario, you would use tools.

# Define the individual agents that will run in parallel
weather_fetcher = Agent(
   name="weather_fetcher",
   model="gemini-2.0-flash-exp",
   instruction="Fetch the weather for the given location and return
only the weather report.",
   output_key="weather_data" # The result will be stored in
session.state["weather_data"]
)

news_fetcher = Agent(
   name="news_fetcher",
   model="gemini-2.0-flash-exp",
   instruction="Fetch the top news story for the given topic and
return only that story.",
   output_key="news_data"      # The result will be stored in
session.state["news_data"]
)

# Create the ParallelAgent to orchestrate the sub-agents
data_gatherer = ParallelAgent(
   name="data_gatherer",
   sub_agents=[
       weather_fetcher,
       news_fetcher
   ]
)


The provided code segment exemplifies the "Agent as a Tool" paradigm within the
Google ADK, enabling an agent to utilize the capabilities of another agent in a manner
analogous to function invocation. Specifically, the code defines an image generation
system using Google's LlmAgent and AgentTool classes. It consists of two agents: a
parent artist_agent and a sub-agent image_generator_agent. The generate_image

                                                                                    14

function is a simple tool that simulates image creation, returning mock image data.
The image_generator_agent is responsible for using this tool based on a text prompt it
receives. The artist_agent's role is to first invent a creative image prompt. It then calls
the image_generator_agent through an AgentTool wrapper. The AgentTool acts as a
bridge, allowing one agent to use another agent as a tool. When the artist_agent calls
the image_tool, the AgentTool invokes the image_generator_agent with the artist's
invented prompt. The image_generator_agent then uses the generate_image function
with that prompt. Finally, the generated image (or mock data) is returned back up
through the agents. This architecture demonstrates a layered agent system where a
higher-level agent orchestrates a lower-level, specialized agent to perform a task.



 from google.adk.agents import LlmAgent
 from google.adk.tools import agent_tool
 from google.genai import types

 # 1. A simple function tool for the core capability.
 # This follows the best practice of separating actions from
 reasoning.
 def generate_image(prompt: str) -> dict:
    """
    Generates an image based on a textual prompt.

    Args:
        prompt: A detailed description of the image to generate.

    Returns:
        A dictionary with the status and the generated image bytes.
