# Chapter 16: Resource-Aware Optimization

> From *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems* by Antonio Gulli.
> Source: [`docs/Agentic_Design_Patterns.pdf`](../Agentic_Design_Patterns.pdf) (extracted 2026-04-23 via `pdftotext -layout`).
> Overview: [`docs/gulli-book-overview.md`](../gulli-book-overview.md).
> Our platform's status on this pattern: see [`wiki/patterns/`](../../wiki/patterns/).

---

        tools=await toolset.get_tools(),
    )



This Python code defines an asynchronous function `create_agent` that constructs an
ADK LlmAgent. It begins by initializing a `CalendarToolset` using the provided client
credentials to access the Google Calendar API. Subsequently, an `LlmAgent` instance
is created, configured with a specified Gemini model, a descriptive name, and
instructions for managing a user's calendar. The agent is furnished with calendar tools
from the `CalendarToolset`, enabling it to interact with the Calendar API and respond
to user queries regarding calendar states or modifications. The agent's instructions
dynamically incorporate the current date for temporal context. To illustrate how an
agent is constructed, let's examine a key section from the calendar_agent found in the
A2A samples on GitHub.

The code below shows how the agent is defined with its specific instructions and
tools. Please note that only the code required to explain this functionality is shown;
you can access the complete file here:


                                                                                         9

https://github.com/a2aproject/a2a-samples/blob/main/samples/python/agents/birthda
y_planner_adk/calendar_agent/__main__.py

def main(host: str, port: int):
   # Verify an API key is set.
   # Not required if using Vertex AI APIs.
   if os.getenv('GOOGLE_GENAI_USE_VERTEXAI') != 'TRUE' and not
os.getenv(
       'GOOGLE_API_KEY'
   ):
       raise ValueError(
           'GOOGLE_API_KEY environment variable not set and '
           'GOOGLE_GENAI_USE_VERTEXAI is not TRUE.'
       )

   skill = AgentSkill(
       id='check_availability',
       name='Check Availability',
       description="Checks a user's availability for a time using
their Google Calendar",
       tags=['calendar'],
       examples=['Am I free from 10am to 11am tomorrow?'],
   )

    agent_card = AgentCard(
        name='Calendar Agent',
        description="An agent that can manage a user's calendar",
        url=f'http://{host}:{port}/',
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )

    adk_agent = asyncio.run(create_agent(
        client_id=os.getenv('GOOGLE_CLIENT_ID'),
        client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    ))
    runner = Runner(
        app_name=agent_card.name,
        agent=adk_agent,
        artifact_service=InMemoryArtifactService(),
        session_service=InMemorySessionService(),
        memory_service=InMemoryMemoryService(),
    )


                                                                               10

    agent_executor = ADKAgentExecutor(runner, agent_card)

    async def handle_auth(request: Request) -> PlainTextResponse:
        await agent_executor.on_auth_callback(
            str(request.query_params.get('state')), str(request.url)
        )
        return PlainTextResponse('Authentication successful.')

    request_handler = DefaultRequestHandler(
        agent_executor=agent_executor, task_store=InMemoryTaskStore()
    )

    a2a_app = A2AStarletteApplication(
        agent_card=agent_card, http_handler=request_handler
    )
    routes = a2a_app.routes()
    routes.append(
        Route(
            path='/authenticate',
            methods=['GET'],
            endpoint=handle_auth,
        )
    )
    app = Starlette(routes=routes)

    uvicorn.run(app, host=host, port=port)

if __name__ == '__main__':
   main()



This Python code demonstrates setting up an A2A-compliant "Calendar Agent" for
checking user availability using Google Calendar. It involves verifying API keys or
Vertex AI configurations for authentication purposes. The agent's capabilities,
including the "check_availability" skill, are defined within an AgentCard, which also
specifies the agent's network address. Subsequently, an ADK agent is created,
configured with in-memory services for managing artifacts, sessions, and memory.
The code then initializes a Starlette web application, incorporates an authentication
callback and the A2A protocol handler, and executes it using Uvicorn to expose the
agent via HTTP.

These examples illustrate the process of building an A2A-compliant agent, from
defining its capabilities to running it as a web service. By utilizing Agent Cards and
ADK, developers can create interoperable AI agents capable of integrating with tools

                                                                                        11

like Google Calendar. This practical approach demonstrates the application of A2A in
establishing a multi-agent ecosystem.

Further exploration of A2A is recommended through the code demonstration at
https://www.trickle.so/blog/how-to-build-google-a2a-project. Resources available at
this link include sample A2A clients and servers in Python and JavaScript, multi-agent
web applications, command-line interfaces, and example implementations for various
agent frameworks.


At a Glance
What: Individual AI agents, especially those built on different frameworks, often
struggle with complex, multi-faceted problems on their own. The primary challenge is
the lack of a common language or protocol that allows them to communicate and
collaborate effectively. This isolation prevents the creation of sophisticated systems
where multiple specialized agents can combine their unique skills to solve larger tasks.
Without a standardized approach, integrating these disparate agents is costly,
time-consuming, and hinders the development of more powerful, cohesive AI
solutions.

Why: The Inter-Agent Communication (A2A) protocol provides an open, standardized
solution for this problem. It is an HTTP-based protocol that enables interoperability,
allowing distinct AI agents to coordinate, delegate tasks, and share information
seamlessly, regardless of their underlying technology. A core component is the Agent
Card, a digital identity file that describes an agent's capabilities, skills, and
communication endpoints, facilitating discovery and interaction. A2A defines various
interaction mechanisms, including synchronous and asynchronous communication, to
support diverse use cases. By creating a universal standard for agent collaboration,
A2A fosters a modular and scalable ecosystem for building complex, multi-agent
Agentic systems.

Rule of thumb: Use this pattern when you need to orchestrate collaboration between
two or more AI agents, especially if they are built using different frameworks (e.g.,
Google ADK, LangGraph, CrewAI). It is ideal for building complex, modular
applications where specialized agents handle specific parts of a workflow, such as
delegating data analysis to one agent and report generation to another. This pattern is
also essential when an agent needs to dynamically discover and consume the
capabilities of other agents to complete a task.



                                                                                     12

Visual summary




                   Fig.2: A2A inter-agent communication pattern



Key Takeaways
Key Takeaways:

  ●​ The Google A2A protocol is an open, HTTP-based standard that facilitates
     communication and collaboration between AI agents built with different
     frameworks.
  ●​ An AgentCard serves as a digital identifier for an agent, allowing for automatic
     discovery and understanding of its capabilities by other agents.
  ●​ A2A offers both synchronous request-response interactions (using
     `tasks/send`) and streaming updates (using `tasks/sendSubscribe`) to
     accommodate varying communication needs.
  ●​ The protocol supports multi-turn conversations, including an `input-required`

                                                                                    13

      state, which allows agents to request additional information and maintain
      context during interactions.
   ●​ A2A encourages a modular architecture where specialized agents can operate
      independently on different ports, enabling system scalability and distribution.
   ●​ Tools such as Trickle AI aid in visualizing and tracking A2A communications,
      which helps developers monitor, debug, and optimize multi-agent systems.
   ●​ While A2A is a high-level protocol for managing tasks and workflows between
      different agents, the Model Context Protocol (MCP) provides a standardized
      interface for LLMs to interface with external resources


Conclusions
The Inter-Agent Communication (A2A) protocol establishes a vital, open standard to
overcome the inherent isolation of individual AI agents. By providing a common
HTTP-based framework, it ensures seamless collaboration and interoperability
between agents built on different platforms, such as Google ADK, LangGraph, or
CrewAI. A core component is the Agent Card, which serves as a digital identity, clearly
defining an agent's capabilities and enabling dynamic discovery by other agents. The
protocol's flexibility supports various interaction patterns, including synchronous
requests, asynchronous polling, and real-time streaming, catering to a wide range of
application needs.

This enables the creation of modular and scalable architectures where specialized
agents can be combined to orchestrate complex automated workflows. Security is a
fundamental aspect, with built-in mechanisms like mTLS and explicit authentication
requirements to protect communications. While complementing other standards like
MCP, A2A's unique focus is on the high-level coordination and task delegation
between agents. The strong backing from major technology companies and the
availability of practical implementations highlight its growing importance. This
protocol paves the way for developers to build more sophisticated, distributed, and
intelligent multi-agent systems. Ultimately, A2A is a foundational pillar for fostering an
innovative and interoperable ecosystem of collaborative AI.


References
 1.​ Chen, B. (2025, April 22). How to Build Your First Google A2A Project: A
     Step-by-Step Tutorial. Trickle.so Blog.
     https://www.trickle.so/blog/how-to-build-google-a2a-project
 2.​ Google A2A GitHub Repository. https://github.com/google-a2a/A2A

                                                                                        14

3.​ Google Agent Development Kit (ADK) https://google.github.io/adk-docs/
4.​ Getting Started with Agent-to-Agent (A2A) Protocol:
    https://codelabs.developers.google.com/intro-a2a-purchasing-concierge#0
5.​ Google AgentDiscovery - https://a2a-protocol.org/latest/
6.​ Communication between different AI frameworks such as LangGraph, CrewAI,
    and Google ADK https://www.trickle.so/blog/how-to-build-google-a2a-project
7.​ Designing Collaborative Multi-Agent Systems with the A2A Protocol
    https://www.oreilly.com/radar/designing-collaborative-multi-agent-systems-with-
    the-a2a-protocol/




                                                                                 15

Chapter 16: Resource-Aware
Optimization
Resource-Aware Optimization enables intelligent agents to dynamically monitor and
manage computational, temporal, and financial resources during operation. This
differs from simple planning, which primarily focuses on action sequencing.
Resource-Aware Optimization requires agents to make decisions regarding action
execution to achieve goals within specified resource budgets or to optimize efficiency.
This involves choosing between more accurate but expensive models and faster,
lower-cost ones, or deciding whether to allocate additional compute for a more
refined response versus returning a quicker, less detailed answer.

For example, consider an agent tasked with analyzing a large dataset for a financial
analyst. If the analyst needs a preliminary report immediately, the agent might use a
faster, more affordable model to quickly summarize key trends. However, if the analyst
requires a highly accurate forecast for a critical investment decision and has a larger
budget and more time, the agent would allocate more resources to utilize a powerful,
slower, but more precise predictive model. A key strategy in this category is the
fallback mechanism, which acts as a safeguard when a preferred model is unavailable
due to being overloaded or throttled. To ensure graceful degradation, the system
automatically switches to a default or more affordable model, maintaining service
continuity instead of failing completely.


Practical Applications & Use Cases
Practical use cases include:

●​ Cost-Optimized LLM Usage: An agent deciding whether to use a large,
   expensive LLM for complex tasks or a smaller, more affordable one for simpler
   queries, based on a budget constraint.
●​ Latency-Sensitive Operations: In real-time systems, an agent chooses a faster
   but potentially less comprehensive reasoning path to ensure a timely response.
●​ Energy Efficiency: For agents deployed on edge devices or with limited power,
   optimizing their processing to conserve battery life.
●​ Fallback for service reliability: An agent automatically switches to a backup
   model when the primary choice is unavailable, ensuring service continuity and
   graceful degradation.

                                                                                      1

 ●​ Data Usage Management: An agent opting for summarized data retrieval
    instead of full dataset downloads to save bandwidth or storage.
 ●​ Adaptive Task Allocation: In multi-agent systems, agents self-assign tasks
    based on their current computational load or available time.

Hands-On Code Example
An intelligent system for answering user questions can assess the difficulty of each
question. For simple queries, it utilizes a cost-effective language model such as
Gemini Flash. For complex inquiries, a more powerful, but expensive, language model
(like Gemini Pro) is considered. The decision to use the more powerful model also
depends on resource availability, specifically budget and time constraints. This system
dynamically selects appropriate models.

For example, consider a travel planner built with a hierarchical agent. The high-level
planning, which involves understanding a user's complex request, breaking it down
into a multi-step itinerary, and making logical decisions, would be managed by a
sophisticated and more powerful LLM like Gemini Pro. This is the "planner" agent that
requires a deep understanding of context and the ability to reason.

However, once the plan is established, the individual tasks within that plan, such as
looking up flight prices, checking hotel availability, or finding restaurant reviews, are
essentially simple, repetitive web queries. These "tool function calls" can be executed
by a faster and more affordable model like Gemini Flash. It is easier to visualize why
the affordable model can be used for these straightforward web searches, while the
intricate planning phase requires the greater intelligence of the more advanced model
to ensure a coherent and logical travel plan.

Google's ADK supports this approach through its multi-agent architecture, which
allows for modular and scalable applications. Different agents can handle specialized
tasks. Model flexibility enables the direct use of various Gemini models, including both
Gemini Pro and Gemini Flash, or integration of other models through LiteLLM. The
ADK's orchestration capabilities support dynamic, LLM-driven routing for adaptive
behavior. Built-in evaluation features allow systematic assessment of agent
performance, which can be used for system refinement (see the Chapter on
Evaluation and Monitoring).

Next, two agents with identical setup but utilizing different models and costs will be
defined.


                                                                                         2

# Conceptual Python-like structure, not runnable code

from google.adk.agents import Agent
# from google.adk.models.lite_llm import LiteLlm # If using models
not directly supported by ADK's default Agent

# Agent using the more expensive Gemini Pro 2.5
gemini_pro_agent = Agent(
   name="GeminiProAgent",
   model="gemini-2.5-pro", # Placeholder for actual model name if
different
   description="A highly capable agent for complex queries.",
   instruction="You are an expert assistant for complex
problem-solving."
)

# Agent using the less expensive Gemini Flash 2.5
gemini_flash_agent = Agent(
   name="GeminiFlashAgent",
   model="gemini-2.5-flash", # Placeholder for actual model name if
different
   description="A fast and efficient agent for simple queries.",
   instruction="You are a quick assistant for straightforward
questions."
)



A Router Agent can direct queries based on simple metrics like query length, where
shorter queries go to less expensive models and longer queries to more capable
models. However, a more sophisticated Router Agent can utilize either LLM or ML
models to analyze query nuances and complexity. This LLM router can determine
which downstream language model is most suitable. For example, a query requesting
a factual recall is routed to a flash model, while a complex query requiring deep
analysis is routed to a pro model.

Optimization techniques can further enhance the LLM router's effectiveness. Prompt
tuning involves crafting prompts to guide the router LLM for better routing decisions.
Fine-tuning the LLM router on a dataset of queries and their optimal model choices
improves its accuracy and efficiency. This dynamic routing capability balances
response quality with cost-effectiveness.



                                                                                         3

# Conceptual Python-like structure, not runnable code

from google.adk.agents import Agent, BaseAgent
from google.adk.events import Event
from google.adk.agents.invocation_context import InvocationContext
import asyncio

class QueryRouterAgent(BaseAgent):
   name: str = "QueryRouter"
   description: str = "Routes user queries to the appropriate LLM
agent based on complexity."

   async def _run_async_impl(self, context: InvocationContext) ->
AsyncGenerator[Event, None]:
       user_query = context.current_message.text # Assuming text
input
       query_length = len(user_query.split()) # Simple metric: number
of words

       if query_length < 20: # Example threshold for simplicity vs.
complexity
           print(f"Routing to Gemini Flash Agent for short query
(length: {query_length})")
           # In a real ADK setup, you would 'transfer_to_agent' or
directly invoke
           # For demonstration, we'll simulate a call and yield its
response
           response = await
gemini_flash_agent.run_async(context.current_message)
           yield Event(author=self.name, content=f"Flash Agent
processed: {response}")
       else:
           print(f"Routing to Gemini Pro Agent for long query
(length: {query_length})")
           response = await
gemini_pro_agent.run_async(context.current_message)
           yield Event(author=self.name, content=f"Pro Agent
processed: {response}")



The Critique Agent evaluates responses from language models, providing feedback
that serves several functions. For self-correction, it identifies errors or
inconsistencies, prompting the answering agent to refine its output for improved


                                                                                   4

quality. It also systematically assesses responses for performance monitoring,
tracking metrics like accuracy and relevance, which are used for optimization.

Additionally, its feedback can signal reinforcement learning or fine-tuning; consistent
identification of inadequate Flash model responses, for instance, can refine the router
agent's logic. While not directly managing the budget, the Critique Agent contributes
to indirect budget management by identifying suboptimal routing choices, such as
directing simple queries to a Pro model or complex queries to a Flash model, which
leads to poor results. This informs adjustments that improve resource allocation and
cost savings.

The Critique Agent can be configured to review either only the generated text from
the answering agent or both the original query and the generated text, enabling a
comprehensive evaluation of the response's alignment with the initial question.

CRITIC_SYSTEM_PROMPT = """
You are the **Critic Agent**, serving as the quality assurance arm of
our collaborative research assistant system. Your primary function is
to **meticulously review and challenge** information from the
Researcher Agent, guaranteeing **accuracy, completeness, and unbiased
presentation**.
Your duties encompass:
* **Assessing research findings** for factual correctness,
thoroughness, and potential leanings.
* **Identifying any missing data** or inconsistencies in reasoning.
* **Raising critical questions** that could refine or expand the
current understanding.
* **Offering constructive suggestions** for enhancement or exploring
different angles.
* **Validating that the final output is comprehensive** and balanced.
All criticism must be constructive. Your goal is to fortify the
research, not invalidate it. Structure your feedback clearly, drawing
attention to specific points for revision. Your overarching aim is to
ensure the final research product meets the highest possible quality
standards.
"""



The Critic Agent operates based on a predefined system prompt that outlines its role,
responsibilities, and feedback approach. A well-designed prompt for this agent must
clearly establish its function as an evaluator. It should specify the areas for critical
focus and emphasize providing constructive feedback rather than mere dismissal. The


                                                                                       5

prompt should also encourage the identification of both strengths and weaknesses,
and it must guide the agent on how to structure and present its feedback.


Hands-On Code with OpenAI
This system uses a resource-aware optimization strategy to handle user queries
efficiently. It first classifies each query into one of three categories to determine the
most appropriate and cost-effective processing pathway. This approach avoids
wasting computational resources on simple requests while ensuring complex queries
get the necessary attention. The three categories are:

   ●​ simple: For straightforward questions that can be answered directly without
      complex reasoning or external data.
   ●​ reasoning: For queries that require logical deduction or multi-step thought
      processes, which are routed to more powerful models.
   ●​ internet_search: For questions needing current information, which
      automatically triggers a Google Search to provide an up-to-date answer.

The code is under the MIT license and available on Github:
(https://github.com/mahtabsyed/21-Agentic-Patterns/blob/main/16_Resource_Aware_
Opt_LLM_Reflection_v2.ipynb)

 # MIT License
 # Copyright (c) 2025 Mahtab Syed
 # https://www.linkedin.com/in/mahtabsyed/

 import os
 REDACTED_a7b84d63quests
 import json
 from dotenv import load_dotenv
 from openai import OpenAI

 # Load environment variables
 load_dotenv()
 OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
 GOOGLE_CUSTOM_SEARCH_API_KEY =
 os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY")
 GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")

 if not OPENAI_API_KEY or not GOOGLE_CUSTOM_SEARCH_API_KEY or not
 GOOGLE_CSE_ID:
    raise ValueError(

                                                                                            6

       "Please set OPENAI_API_KEY, GOOGLE_CUSTOM_SEARCH_API_KEY, and
GOOGLE_CSE_ID in your .env file."
   )

client = OpenAI(api_key=OPENAI_API_KEY)

# --- Step 1: Classify the Prompt ---
def classify_prompt(prompt: str) -> dict:
   system_message = {
       "role": "system",
       "content": (
           "You are a classifier that analyzes user prompts and
returns one of three categories ONLY:\n\n"
           "- simple\n"
           "- reasoning\n"
           "- internet_search\n\n"
           "Rules:\n"
           "- Use 'simple' for direct factual questions that need no
reasoning or current events.\n"
           "- Use 'reasoning' for logic, math, or multi-step
inference questions.\n"
           "- Use 'internet_search' if the prompt refers to current
events, recent data, or things not in your training data.\n\n"
           "Respond ONLY with JSON like:\n"
           '{ "classification": "simple" }'
       ),
   }

  user_message = {"role": "user", "content": prompt}

   response = client.chat.completions.create(
       model="gpt-4o", messages=[system_message, user_message],
temperature=1
   )

  reply = response.choices[0].message.content
  return json.loads(reply)

# --- Step 2: Google Search ---
def google_search(query: str, num_results=1) -> list:
   url = "https://www.googleapis.com/customsearch/v1"
   params = {
       "key": GOOGLE_CUSTOM_SEARCH_API_KEY,
       "cx": GOOGLE_CSE_ID,
       "q": query,
       "num": num_results,
   }

                                                                       7

  try:
      response = requests.get(url, params=params)
      response.raise_for_status()
      results = response.json()


      if "items" in results and results["items"]:
          return [
              {
                  "title": item.get("title"),
                  "snippet": item.get("snippet"),
                  "link": item.get("link"),
              }
              for item in results["items"]
          ]
      else:
          return []
  except requests.exceptions.RequestException as e:
      return {"error": str(e)}

# --- Step 3: Generate Response ---
def generate_response(prompt: str, classification: str,
search_results=None) -> str:
   if classification == "simple":
       model = "gpt-4o-mini"
       full_prompt = prompt
   elif classification == "reasoning":
       model = "o4-mini"
       full_prompt = prompt
   elif classification == "internet_search":
       model = "gpt-4o"
       # Convert each search result dict to a readable string
       if search_results:
           search_context = "\n".join(
               [
                   f"Title: {item.get('title')}\nSnippet:
{item.get('snippet')}\nLink: {item.get('link')}"
                   for item in search_results
               ]
           )
       else:
           search_context = "No search results found."
       full_prompt = f"""Use the following web results to answer the
user query:

{search_context}

                                                                       8

Query: {prompt}"""

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": full_prompt}],
        temperature=1,
    )

    return response.choices[0].message.content, model

# --- Step 4: Combined Router ---
def handle_prompt(prompt: str) -> dict:
   classification_result = classify_prompt(prompt)

   # print("\n    🔍
   # Remove or comment out the next line to avoid duplicate printing
                 Classification Result:", classification_result)
   classification = classification_result["classification"]

    search_results = None
    if classification == "internet_search":

        # print("\n    🔍
        search_results = google_search(prompt)
                      Search Results:", search_results)

   answer, model = generate_response(prompt, classification,
search_results)
   return {"classification": classification, "response": answer,
"model": model}
test_prompt = "What is the capital of Australia?"
# test_prompt = "Explain the impact of quantum computing on
cryptography."
# test_prompt = "When does the Australian Open 2026 start, give me
full date?"


print("  🔍
result = handle_prompt(test_prompt)

         🧠Classification:", result["classification"])
