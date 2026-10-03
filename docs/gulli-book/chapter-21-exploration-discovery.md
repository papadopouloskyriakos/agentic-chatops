# Chapter 21: Exploration and Discovery

> From *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems* by Antonio Gulli.
> Source: [`docs/Agentic_Design_Patterns.pdf`](../Agentic_Design_Patterns.pdf) (extracted 2026-04-23 via `pdftotext -layout`).
> Overview: [`docs/gulli-book-overview.md`](../gulli-book-overview.md).
> Our platform's status on this pattern: see [`wiki/patterns/`](../../wiki/patterns/).

---

# --- 0. Configuration and Setup ---
# Loads the OPENAI_API_KEY from the .env file.
load_dotenv()

# The ChatOpenAI client automatically picks up the API key from the
environment.
llm = ChatOpenAI(temperature=0.5, model="gpt-4o-mini")

# --- 1. Task Management System ---

class Task(BaseModel):
   """Represents a single task in the system."""
   id: str
   description: str
   priority: Optional[str] = None # P0, P1, P2
   assigned_to: Optional[str] = None # Name of the worker

class SuperSimpleTaskManager:
   """An efficient and robust in-memory task manager."""
   def __init__(self):
       # Use a dictionary for O(1) lookups, updates, and deletions.
       self.tasks: Dict[str, Task] = {}
       self.next_task_id = 1

    def create_task(self, description: str) -> Task:
        """Creates and stores a new task."""
        task_id = f"TASK-{self.next_task_id:03d}"
        new_task = Task(id=task_id, description=description)
        self.tasks[task_id] = new_task
        self.next_task_id += 1


                                                                                      3

      print(f"DEBUG: Task created - {task_id}: {description}")
      return new_task

   def update_task(self, task_id: str, **kwargs) -> Optional[Task]:
       """Safely updates a task using Pydantic's model_copy."""
       task = self.tasks.get(task_id)
       if task:
           # Use model_copy for type-safe updates.
           update_data = {k: v for k, v in kwargs.items() if v is not
None}
           updated_task = task.model_copy(update=update_data)
           self.tasks[task_id] = updated_task
           print(f"DEBUG: Task {task_id} updated with {update_data}")
           return updated_task

      print(f"DEBUG: Task {task_id} not found for update.")
      return None

  def list_all_tasks(self) -> str:
      """Lists all tasks currently in the system."""
      if not self.tasks:
          return "No tasks in the system."

      task_strings = []
      for task in self.tasks.values():
          task_strings.append(
              f"ID: {task.id}, Desc: '{task.description}', "
              f"Priority: {task.priority or 'N/A'}, "
              f"Assigned To: {task.assigned_to or 'N/A'}"
          )
      return "Current Tasks:\n" + "\n".join(task_strings)

task_manager = SuperSimpleTaskManager()

# --- 2. Tools for the Project Manager Agent ---

# Use Pydantic models for tool arguments for better validation and
clarity.
class CreateTaskArgs(BaseModel):
   description: str = Field(description="A detailed description of
the task.")

class PriorityArgs(BaseModel):
   task_id: str = Field(description="The ID of the task to update,
e.g., 'TASK-001'.")
   priority: str = Field(description="The priority to set. Must be
one of: 'P0', 'P1', 'P2'.")

                                                                        4

class AssignWorkerArgs(BaseModel):
   task_id: str = Field(description="The ID of the task to update,
e.g., 'TASK-001'.")
   worker_name: str = Field(description="The name of the worker to
assign the task to.")

def create_new_task_tool(description: str) -> str:
   """Creates a new project task with the given description."""
   task = task_manager.create_task(description)
   return f"Created task {task.id}: '{task.description}'."

def assign_priority_to_task_tool(task_id: str, priority: str) -> str:
   """Assigns a priority (P0, P1, P2) to a given task ID."""
   if priority not in ["P0", "P1", "P2"]:
       return "Invalid priority. Must be P0, P1, or P2."
   task = task_manager.update_task(task_id, priority=priority)
   return f"Assigned priority {priority} to task {task.id}." if task
else f"Task {task_id} not found."

def assign_task_to_worker_tool(task_id: str, worker_name: str) ->
str:
   """Assigns a task to a specific worker."""
   task = task_manager.update_task(task_id, assigned_to=worker_name)
   return f"Assigned task {task.id} to {worker_name}." if task else
f"Task {task_id} not found."

# All tools the PM agent can use
pm_tools = [
   Tool(
       name="create_new_task",
       func=create_new_task_tool,
       description="Use this first to create a new task and get its
ID.",
       args_schema=CreateTaskArgs
   ),
   Tool(
       name="assign_priority_to_task",
       func=assign_priority_to_task_tool,
       description="Use this to assign a priority to a task after it
has been created.",
       args_schema=PriorityArgs
   ),
   Tool(
       name="assign_task_to_worker",
       func=assign_task_to_worker_tool,
       description="Use this to assign a task to a specific worker

                                                                        5

after it has been created.",
       args_schema=AssignWorkerArgs
   ),
   Tool(
       name="list_all_tasks",
       func=task_manager.list_all_tasks,
       description="Use this to list all current tasks and their
status."
   ),
]

# --- 3. Project Manager Agent Definition ---

pm_prompt_template = ChatPromptTemplate.from_messages([
   ("system", """You are a focused Project Manager LLM agent. Your
goal is to manage project tasks efficiently.

   When you receive a new task request, follow these steps:
   1. First, create the task with the given description using the
`create_new_task` tool. You must do this first to get a `task_id`.
   2. Next, analyze the user's request to see if a priority or an
assignee is mentioned.
       - If a priority is mentioned (e.g., "urgent", "ASAP",
"critical"), map it to P0. Use `assign_priority_to_task`.
       - If a worker is mentioned, use `assign_task_to_worker`.
   3. If any information (priority, assignee) is missing, you must
make a reasonable default assignment (e.g., assign P1 priority and
assign to 'Worker A').
   4. Once the task is fully processed, use `list_all_tasks` to show
the final state.

     Available workers: 'Worker A', 'Worker B', 'Review Team'
     Priority levels: P0 (highest), P1 (medium), P2 (lowest)
     """),
     ("placeholder", "{chat_history}"),
     ("human", "{input}"),
     ("placeholder", "{agent_scratchpad}")
])

# Create the agent executor
pm_agent = create_react_agent(llm, pm_tools, pm_prompt_template)
pm_agent_executor = AgentExecutor(
   agent=pm_agent,
   tools=pm_tools,
   verbose=True,
   handle_parsing_errors=True,
   memory=ConversationBufferMemory(memory_key="chat_history",

                                                                       6

return_messages=True)
)

# --- 4. Simple Interaction Flow ---

async def run_simulation():
   print("--- Project Manager Simulation ---")

   # Scenario 1: Handle a new, urgent feature request
   print("\n[User Request] I need a new login system implemented
ASAP. It should be assigned to Worker B.")
   await pm_agent_executor.ainvoke({"input": "Create a task to
implement a new login system. It's urgent and should be assigned to
Worker B."})

    print("\n" + "-"*60 + "\n")

   # Scenario 2: Handle a less urgent content update with fewer
details
   print("[User Request] We need to review the marketing website
content.")
   await pm_agent_executor.ainvoke({"input": "Manage a new task:
Review marketing website content."})

    print("\n--- Simulation Complete ---")

# Run the simulation
if __name__ == "__main__":
   asyncio.run(run_simulation())



This code implements a simple task management system using Python and
LangChain, designed to simulate a project manager agent powered by a large
language model.

The system employs a SuperSimpleTaskManager class to efficiently manage tasks
within memory, utilizing a dictionary structure for rapid data retrieval. Each task is
represented by a Task Pydantic model, which encompasses attributes such as a
unique identifier, a descriptive text, an optional priority level (P0, P1, P2), and an
optional assignee designation.Memory usage varies based on task type, the number
of workers, and other contributing factors. The task manager provides methods for
task creation, task modification, and retrieval of all tasks.



                                                                                         7

The agent interacts with the task manager via a defined set of Tools. These tools
facilitate the creation of new tasks, the assignment of priorities to tasks, the allocation
of tasks to personnel, and the listing of all tasks. Each tool is encapsulated to enable
interaction with an instance of the SuperSimpleTaskManager. Pydantic models are
utilized to delineate the requisite arguments for the tools, thereby ensuring data
validation.

An AgentExecutor is configured with the language model, the toolset, and a
conversation memory component to maintain contextual continuity. A specific
ChatPromptTemplate is defined to direct the agent's behavior in its project
management role. The prompt instructs the agent to initiate by creating a task,
subsequently assigning priority and personnel as specified, and concluding with a
comprehensive task list. Default assignments, such as P1 priority and 'Worker A', are
stipulated within the prompt for instances where information is absent.

The code incorporates a simulation function (run_simulation) of asynchronous nature
to demonstrate the agent's operational capacity. The simulation executes two distinct
scenarios: the management of an urgent task with designated personnel, and the
management of a less urgent task with minimal input. The agent's actions and logical
processes are outputted to the console due to the activation of verbose=True within
the AgentExecutor.


At a Glance
What: AI agents operating in complex environments face a multitude of potential
actions, conflicting goals, and finite resources. Without a clear method to determine
their next move, these agents risk becoming inefficient and ineffective. This can lead
to significant operational delays or a complete failure to accomplish primary
objectives. The core challenge is to manage this overwhelming number of choices to
ensure the agent acts purposefully and logically.

Why: The Prioritization pattern provides a standardized solution for this problem by
enabling agents to rank tasks and goals. This is achieved by establishing clear criteria
such as urgency, importance, dependencies, and resource cost. The agent then
evaluates each potential action against these criteria to determine the most critical
and timely course of action. This Agentic capability allows the system to dynamically
adapt to changing circumstances and manage constrained resources effectively. By
focusing on the highest-priority items, the agent's behavior becomes more intelligent,
robust, and aligned with its strategic goals.


                                                                                          8

Rule of thumb: Use the Prioritization pattern when an Agentic system must
autonomously manage multiple, often conflicting, tasks or goals under resource
constraints to operate effectively in a dynamic environment.

Visual summary:




                          Fig.1: Prioritization Design pattern



Key Takeaways
●​ Prioritization enables AI agents to function effectively in complex, multi-faceted
   environments.
●​ Agents utilize established criteria such as urgency, importance, and
   dependencies to evaluate and rank tasks.
●​ Dynamic re-prioritization allows agents to adjust their operational focus in
   response to real-time changes.
●​ Prioritization occurs at various levels, encompassing overarching strategic
   objectives and immediate tactical decisions.
                                                                                        9

●​ Effective prioritization results in increased efficiency and improved operational
    robustness of AI agents.

Conclusions
In conclusion, the prioritization pattern is a cornerstone of effective agentic AI,
equipping systems to navigate the complexities of dynamic environments with
purpose and intelligence. It allows an agent to autonomously evaluate a multitude of
conflicting tasks and goals, making reasoned decisions about where to focus its
limited resources. This agentic capability moves beyond simple task execution,
enabling the system to act as a proactive, strategic decision-maker. By weighing
criteria such as urgency, importance, and dependencies, the agent demonstrates a
sophisticated, human-like reasoning process.

A key feature of this agentic behavior is dynamic re-prioritization, which grants the
agent the autonomy to adapt its focus in real-time as conditions change. As
demonstrated in the code example, the agent interprets ambiguous requests,
autonomously selects and uses the appropriate tools, and logically sequences its
actions to fulfill its objectives. This ability to self-manage its workflow is what
separates a true agentic system from a simple automated script. Ultimately, mastering
prioritization is fundamental for creating robust and intelligent agents that can
operate effectively and reliably in any complex, real-world scenario.


References
1.​ Examining the Security of Artificial Intelligence in Project Management: A Case
    Study of AI-driven Project Scheduling and Resource Allocation in Information
    Systems Projects ; https://www.irejournals.com/paper-details/1706160
2.​ AI-Driven Decision Support Systems in Agile Software Project Management:
    Enhancing Risk Mitigation and Resource Allocation;
    https://www.mdpi.com/2079-8954/13/3/208




                                                                                       10

Chapter 21: Exploration and Discovery
This chapter explores patterns that enable intelligent agents to actively seek out novel
information, uncover new possibilities, and identify unknown unknowns within their
operational environment. Exploration and discovery differ from reactive behaviors or
optimization within a predefined solution space. Instead, they focus on agents
proactively venturing into unfamiliar territories, experimenting with new approaches,
and generating new knowledge or understanding. This pattern is crucial for agents
operating in open-ended, complex, or rapidly evolving domains where static
knowledge or pre-programmed solutions are insufficient. It emphasizes the agent's
capacity to expand its understanding and capabilities.


Practical Applications & Use Cases
AI agents possess the ability to intelligently prioritize and explore, which leads to
applications across various domains. By autonomously evaluating and ordering
potential actions, these agents can navigate complex environments, uncover hidden
insights, and drive innovation. This capacity for prioritized exploration enables them to
optimize processes, discover new knowledge, and generate content.

Examples:

   ●​ Scientific Research Automation: An agent designs and runs experiments,
      analyzes results, and formulates new hypotheses to discover novel materials,
      drug candidates, or scientific principles.
   ●​ Game Playing and Strategy Generation: Agents explore game states,
      discovering emergent strategies or identifying vulnerabilities in game
      environments (e.g., AlphaGo).
   ●​ Market Research and Trend Spotting: Agents scan unstructured data (social
      media, news, reports) to identify trends, consumer behaviors, or market
      opportunities.
   ●​ Security Vulnerability Discovery: Agents probe systems or codebases to find
      security flaws or attack vectors.
   ●​ Creative Content Generation: Agents explore combinations of styles, themes,
      or data to generate artistic pieces, musical compositions, or literary works.
   ●​ Personalized Education and Training: AI tutors prioritize learning paths and
      content delivery based on a student's progress, learning style, and areas
      needing improvement.


                                                                                        1

Google Co-Scientist
An AI co-scientist is an AI system developed by Google Research designed as a
computational scientific collaborator. It assists human scientists in research aspects
such as hypothesis generation, proposal refinement, and experimental design. This
system operates on the Gemini LLM..

The development of the AI co-scientist addresses challenges in scientific research.
These include processing large volumes of information, generating testable
hypotheses, and managing experimental planning. The AI co-scientist supports
researchers by performing tasks that involve large-scale information processing and
synthesis, potentially revealing relationships within data. Its purpose is to augment
human cognitive processes by handling computationally demanding aspects of
early-stage research.

System Architecture and Methodology: The architecture of the AI co-scientist is
based on a multi-agent framework, structured to emulate collaborative and iterative
processes. This design integrates specialized AI agents, each with a specific role in
contributing to a research objective. A supervisor agent manages and coordinates the
activities of these individual agents within an asynchronous task execution framework
that allows for flexible scaling of computational resources.

The core agents and their functions include (see Fig. 1):

   ●​ Generation agent: Initiates the process by producing initial hypotheses
      through literature exploration and simulated scientific debates.
   ●​ Reflection agent: Acts as a peer reviewer, critically assessing the correctness,
      novelty, and quality of the generated hypotheses.
   ●​ Ranking agent: Employs an Elo-based tournament to compare, rank, and
      prioritize hypotheses through simulated scientific debates.
   ●​ Evolution agent: Continuously refines top-ranked hypotheses by simplifying
      concepts, synthesizing ideas, and exploring unconventional reasoning.
   ●​ Proximity agent: Computes a proximity graph to cluster similar ideas and
      assist in exploring the hypothesis landscape.
   ●​ Meta-review agent: Synthesizes insights from all reviews and debates to
      identify common patterns and provide feedback, enabling the system to
      continuously improve.

The system's operational foundation relies on Gemini, which provides language
understanding, reasoning, and generative abilities. The system incorporates
                                                                                         2

"test-time compute scaling," a mechanism that allocates increased computational
resources to iteratively reason and enhance outputs. The system processes and
synthesizes information from diverse sources, including academic literature,
web-based data, and databases.




        Fig. 1: (Courtesy of the Authors) AI Co-Scientist: Ideation to Validation

The system follows an iterative "generate, debate, and evolve" approach mirroring the
scientific method. Following the input of a scientific problem from a human scientist,
the system engages in a self-improving cycle of hypothesis generation, evaluation,
and refinement. Hypotheses undergo systematic assessment, including internal
evaluations among agents and a tournament-based ranking mechanism.

Validation and Results: The AI co-scientist's utility has been demonstrated in several
validation studies, particularly in biomedicine, assessing its performance through
automated benchmarks, expert reviews, and end-to-end wet-lab experiments.

Automated and Expert Evaluation: On the challenging GPQA benchmark, the
system's internal Elo rating was shown to be concordant with the accuracy of its
results, achieving a top-1 accuracy of 78.4% on the difficult "diamond set". Analysis
across over 200 research goals demonstrated that scaling test-time compute
consistently improves the quality of hypotheses, as measured by the Elo rating. On a
curated set of 15 challenging problems, the AI co-scientist outperformed other
state-of-the-art AI models and the "best guess" solutions provided by human experts.
In a small-scale evaluation, biomedical experts rated the co-scientist's outputs as

                                                                                     3

more novel and impactful compared to other baseline models. The system's proposals
for drug repurposing, formatted as NIH Specific Aims pages, were also judged to be of
high quality by a panel of six expert oncologists.

End-to-End Experimental Validation:

Drug Repurposing: For acute myeloid leukemia (AML), the system proposed novel
drug candidates. Some of these, like KIRA6, were completely novel suggestions with
no prior preclinical evidence for use in AML. Subsequent in vitro experiments
confirmed that KIRA6 and other suggested drugs inhibited tumor cell viability at
clinically relevant concentrations in multiple AML cell lines.

 Novel Target Discovery: The system identified novel epigenetic targets for liver
fibrosis. Laboratory experiments using human hepatic organoids validated these
findings, showing that drugs targeting the suggested epigenetic modifiers had
significant anti-fibrotic activity. One of the identified drugs is already FDA-approved
for another condition, opening an opportunity for repurposing.

Antimicrobial Resistance: The AI co-scientist independently recapitulated unpublished
experimental findings. It was tasked to explain why certain mobile genetic elements
(cf-PICIs) are found across many bacterial species. In two days, the system's
top-ranked hypothesis was that cf-PICIs interact with diverse phage tails to expand
their host range. This mirrored the novel, experimentally validated discovery that an
independent research group had reached after more than a decade of research.

Augmentation, and Limitations: The design philosophy behind the AI co-scientist
emphasizes augmentation rather than complete automation of human research.
Researchers interact with and guide the system through natural language, providing
feedback, contributing their own ideas, and directing the AI's exploratory processes in
a "scientist-in-the-loop" collaborative paradigm. However, the system has some
limitations. Its knowledge is constrained by its reliance on open-access literature,
potentially missing critical prior work behind paywalls. It also has limited access to
negative experimental results, which are rarely published but crucial for experienced
scientists. Furthermore, the system inherits limitations from the underlying LLMs,
including the potential for factual inaccuracies or "hallucinations".

Safety: Safety is a critical consideration, and the system incorporates multiple
safeguards. All research goals are reviewed for safety upon input, and generated
hypotheses are also checked to prevent the system from being used for unsafe or
unethical research. A preliminary safety evaluation using 1,200 adversarial research

                                                                                          4

goals found that the system could robustly reject dangerous inputs. To ensure
responsible development, the system is being made available to more scientists
through a Trusted Tester Program to gather real-world feedback.


Hands-On Code Example
Let's look at a concrete example of agentic AI for Exploration and Discovery in action:
Agent Laboratory, a project developed by Samuel Schmidgall under the MIT License.

"Agent Laboratory" is an autonomous research workflow framework designed to
augment human scientific endeavors rather than replace them. This system leverages
specialized LLMs to automate various stages of the scientific research process,
thereby enabling human researchers to dedicate more cognitive resources to
conceptualization and critical analysis.

The framework integrates "AgentRxiv," a decentralized repository for autonomous
research agents. AgentRxiv facilitates the deposition, retrieval, and development of
research outputs

Agent Laboratory guides the research process through distinct phases:

   1.​ Literature Review: During this initial phase, specialized LLM-driven agents are
       tasked with the autonomous collection and critical analysis of pertinent
       scholarly literature. This involves leveraging external databases such as arXiv to
       identify, synthesize, and categorize relevant research, effectively establishing a
       comprehensive knowledge base for the subsequent stages.
   2.​ Experimentation: This phase encompasses the collaborative formulation of
       experimental designs, data preparation, execution of experiments, and analysis
       of results. Agents utilize integrated tools like Python for code generation and
       execution, and Hugging Face for model access, to conduct automated
       experimentation. The system is designed for iterative refinement, where agents
       can adapt and optimize experimental procedures based on real-time outcomes.
   3.​ Report Writing: In the final phase, the system automates the generation of
       comprehensive research reports. This involves synthesizing findings from the
       experimentation phase with insights from the literature review, structuring the
       document according to academic conventions, and integrating external tools
       like LaTeX for professional formatting and figure generation.
   4.​ Knowledge Sharing: AgentRxiv is a platform enabling autonomous research
       agents to share, access, and collaboratively advance scientific discoveries. It


                                                                                          5

      allows agents to build upon previous findings, fostering cumulative research
      progress.

The modular architecture of Agent Laboratory ensures computational flexibility. The
aim is to enhance research productivity by automating tasks while maintaining the
human researcher.

Code analysis: While a comprehensive code analysis is beyond the scope of this
book, I want to provide you with some key insights and encourage you to delve into
the code on your own.

Judgment: In order to emulate human evaluative processes, the system employs a
tripartite agentic judgment mechanism for assessing outputs. This involves the
deployment of three distinct autonomous agents, each configured to evaluate the
production from a specific perspective, thereby collectively mimicking the nuanced
and multi-faceted nature of human judgment. This approach allows for a more robust
and comprehensive appraisal, moving beyond singular metrics to capture a richer
qualitative assessment.

class ReviewersAgent:
   def __init__(self, model="gpt-4o-mini", notes=None,
