# Chapter 15: Inter-Agent Communication (A2A)

> From *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems* by Antonio Gulli.
> Source: [`docs/Agentic_Design_Patterns.pdf`](../Agentic_Design_Patterns.pdf) (extracted 2026-04-23 via `pdftotext -layout`).
> Overview: [`docs/gulli-book-overview.md`](../gulli-book-overview.md).
> Our platform's status on this pattern: see [`wiki/patterns/`](../../wiki/patterns/).

---

vectorstore = Weaviate.from_documents(
   client = client,
   documents = chunks,
   embedding = OpenAIEmbeddings(),
   by_text = False
)

# Define the retriever
retriever = vectorstore.as_retriever()

# Initialize LLM
llm = ChatOpenAI(model_name="gpt-3.5-turbo", temperature=0)

# --- 2. Define the State for LangGraph ---
class RAGGraphState(TypedDict):
   question: str

                                                                       11

  documents: List[Document]
  generation: str

# --- 3. Define the Nodes (Functions) ---

def retrieve_documents_node(state: RAGGraphState) -> RAGGraphState:
   """Retrieves documents based on the user's question."""
   question = state["question"]
   documents = retriever.invoke(question)
   return {"documents": documents, "question": question,
"generation": ""}

def generate_response_node(state: RAGGraphState) -> RAGGraphState:
   """Generates a response using the LLM based on retrieved
documents."""
   question = state["question"]
   documents = state["documents"]

   # Prompt template from the PDF
   template = """You are an assistant for question-answering tasks.
Use the following pieces of retrieved context to answer the question.
If you don't know the answer, just say that you don't know.
Use three sentences maximum and keep the answer concise.
Question: {question}
Context: {context}
Answer:
"""
   prompt = ChatPromptTemplate.from_template(template)

  # Format the context from the documents
  context = "\n\n".join([doc.page_content for doc in documents])

  # Create the RAG chain
  rag_chain = prompt | llm | StrOutputParser()

   # Invoke the chain
   generation = rag_chain.invoke({"context": context, "question":
question})
   return {"question": question, "documents": documents,
"generation": generation}

# --- 4. Build the LangGraph Graph ---

workflow = StateGraph(RAGGraphState)

# Add nodes
workflow.add_node("retrieve", retrieve_documents_node)

                                                                      12

workflow.add_node("generate", generate_response_node)

# Set the entry point
workflow.set_entry_point("retrieve")

# Add edges (transitions)
workflow.add_edge("retrieve", "generate")
workflow.add_edge("generate", END)

# Compile the graph
app = workflow.compile()

# --- 5. Run the RAG Application ---
if __name__ == "__main__":
   print("\n--- Running RAG Query ---")
   query = "What did the president say about Justice Breyer"
   inputs = {"question": query}
   for s in app.stream(inputs):
       print(s)

    print("\n--- Running another RAG Query ---")
    query_2 = "What did the president say about the economy?"
    inputs_2 = {"question": query_2}
    for s in app.stream(inputs_2):
        print(s)



This Python code illustrates a Retrieval-Augmented Generation (RAG) pipeline
implemented with LangChain and LangGraph. The process begins with the creation of
a knowledge base derived from a text document, which is segmented into chunks and
transformed into embeddings. These embeddings are then stored in a Weaviate
vector store, facilitating efficient information retrieval. A StateGraph in LangGraph is
utilized to manage the workflow between two key functions:
`retrieve_documents_node` and `generate_response_node`. The
`retrieve_documents_node` function queries the vector store to identify relevant
document chunks based on the user's input. Subsequently, the
`generate_response_node` function utilizes the retrieved information and a
predefined prompt template to produce a response using an OpenAI Large Language
Model (LLM). The `app.stream` method allows the execution of queries through the
RAG pipeline, demonstrating the system's capacity to generate contextually relevant
outputs.



                                                                                     13

At Glance
What: LLMs possess impressive text generation abilities but are fundamentally limited
by their training data. This knowledge is static, meaning it doesn't include real-time
information or private, domain-specific data. Consequently, their responses can be
outdated, inaccurate, or lack the specific context required for specialized tasks. This
gap restricts their reliability for applications demanding current and factual answers.

Why: The Retrieval-Augmented Generation (RAG) pattern provides a standardized
solution by connecting LLMs to external knowledge sources. When a query is
received, the system first retrieves relevant information snippets from a specified
knowledge base. These snippets are then appended to the original prompt, enriching
it with timely and specific context. This augmented prompt is then sent to the LLM,
enabling it to generate a response that is accurate, verifiable, and grounded in
external data. This process effectively transforms the LLM from a closed-book
reasoner into an open-book one, significantly enhancing its utility and
trustworthiness.

Rule of thumb: Use this pattern when you need an LLM to answer questions or
generate content based on specific, up-to-date, or proprietary information that was
not part of its original training data. It is ideal for building Q&A systems over internal
documents, customer support bots, and applications requiring verifiable, fact-based
responses with citations.

Visual summary




                                                                                         14

Knowledge Retrieval pattern: an AI agent to query and retrieve information from
                            structured databases




                                                                                  15

 Fig. 3: Knowledge Retrieval pattern: an AI agent to find and synthesize information
                from the public internet in response to user queries.


Key Takeaways

●​ Knowledge Retrieval (RAG) enhances LLMs by allowing them to access external,
   up-to-date, and specific information.
●​ The process involves Retrieval (searching a knowledge base for relevant snippets)
   and Augmentation (adding these snippets to the LLM's prompt).
●​ RAG helps LLMs overcome limitations like outdated training data, reduces
   "hallucinations," and enables domain-specific knowledge integration.
●​ RAG allows for attributable answers, as the LLM's response is grounded in
   retrieved sources.
●​ GraphRAG leverages a knowledge graph to understand the relationships between
   different pieces of information, allowing it to answer complex questions that
   require synthesizing data from multiple sources.


                                                                                       16

 ●​ Agentic RAG moves beyond simple information retrieval by using an intelligent
    agent to actively reason about, validate, and refine external knowledge, ensuring
    a more accurate and reliable answer.
 ●​ Practical applications span enterprise search, customer support, legal research,
    and personalized recommendations.

Conclusion
In conclusion, Retrieval-Augmented Generation (RAG) addresses the core limitation of
a Large Language Model's static knowledge by connecting it to external, up-to-date
data sources. The process works by first retrieving relevant information snippets and
then augmenting the user's prompt, enabling the LLM to generate more accurate and
contextually aware responses. This is made possible by foundational technologies like
embeddings, semantic search, and vector databases, which find information based on
meaning rather than just keywords. By grounding outputs in verifiable data, RAG
significantly reduces factual errors and allows for the use of proprietary information,
enhancing trust through citations.

An advanced evolution, Agentic RAG, introduces a reasoning layer that actively
validates, reconciles, and synthesizes retrieved knowledge for even greater reliability.
Similarly, specialized approaches like GraphRAG leverage knowledge graphs to
navigate explicit data relationships, allowing the system to synthesize answers to
highly complex, interconnected queries. This agent can resolve conflicting
information, perform multi-step queries, and use external tools to find missing data.
While these advanced methods add complexity and latency, they drastically improve
the depth and trustworthiness of the final response. Practical applications for these
patterns are already transforming industries, from enterprise search and customer
support to personalized content delivery. Despite the challenges, RAG is a crucial
pattern for making AI more knowledgeable, reliable, and useful. Ultimately, it
transforms LLMs from closed-book conversationalists into powerful, open-book
reasoning tools.


References
 1.​ Lewis, P., et al. (2020). Retrieval-Augmented Generation for Knowledge-Intensive
     NLP Tasks. https://arxiv.org/abs/2005.11401
 2.​ Google AI for Developers Documentation. Retrieval Augmented Generation -
    https://cloud.google.com/vertex-ai/generative-ai/docs/rag-engine/rag-overv
    iew
                                                                                       17

3.​ Retrieval-Augmented Generation with Graphs (GraphRAG),
    https://arxiv.org/abs/2501.00309
4.​ LangChain and LangGraph: Leonie Monigatti, "Retrieval-Augmented Generation
    (RAG): From Theory to LangChain Implementation,"
   https://medium.com/data-science/retrieval-augmented-generation-rag-fro
   m-theory-to-langchain-implementation-4e9bd5f6a4f2
5.​ Google Cloud Vertex AI RAG Corpus
    https://cloud.google.com/vertex-ai/generative-ai/docs/rag-engine/manage-y
    our-rag-corpus#corpus-management




                                                                                 18

Chapter 15: Inter-Agent Communication
(A2A)
Individual AI agents often face limitations when tackling complex, multifaceted
problems, even with advanced capabilities. To overcome this, Inter-Agent
Communication (A2A) enables diverse AI agents, potentially built with different
frameworks, to collaborate effectively. This collaboration involves seamless
coordination, task delegation, and information exchange.

Google's A2A protocol is an open standard designed to facilitate this universal
communication. This chapter will explore A2A, its practical applications, and its
implementation within the Google ADK.


Inter-Agent Communication Pattern Overview
The Agent2Agent (A2A) protocol is an open standard designed to enable
communication and collaboration between different AI agent frameworks. It ensures
interoperability, allowing AI agents developed with technologies like LangGraph,
CrewAI, or Google ADK to work together regardless of their origin or framework
differences.

A2A is supported by a range of technology companies and service providers,
including Atlassian, Box, LangChain, MongoDB, Salesforce, SAP, and ServiceNow.
Microsoft plans to integrate A2A into Azure AI Foundry and Copilot Studio,
demonstrating its commitment to open protocols. Additionally, Auth0 and SAP are
integrating A2A support into their platforms and agents.

As an open-source protocol, A2A welcomes community contributions to facilitate its
evolution and widespread adoption.


Core Concepts of A2A
The A2A protocol provides a structured approach for agent interactions, built upon
several core concepts. A thorough grasp of these concepts is crucial for anyone
developing or integrating with A2A-compliant systems. The foundational pillars of A2A
include Core Actors, Agent Card, Agent Discovery, Communication and Tasks,
Interaction mechanisms, and Security, all of which will be reviewed in detail.

                                                                                     1

Core Actors: A2A involves three main entities:

   ●​ User: Initiates requests for agent assistance.
   ●​ A2A Client (Client Agent): An application or AI agent that acts on the user's
      behalf to request actions or information.
   ●​ A2A Server (Remote Agent): An AI agent or system that provides an HTTP
      endpoint to process client requests and return results. The remote agent
      operates as an "opaque" system, meaning the client does not need to
      understand its internal operational details.

Agent Card: An agent's digital identity is defined by its Agent Card, usually a JSON
file. This file contains key information for client interaction and automatic discovery,
including the agent's identity, endpoint URL, and version. It also details supported
capabilities like streaming or push notifications, specific skills, default input/output
modes, and authentication requirements. Below is an example of an Agent Card for a
WeatherBot.


 {
  "name": "WeatherBot",
  "description": "Provides accurate weather forecasts and historical
 data.",
  "url": "http://weather-service.example.com/a2a",
  "version": "1.0.0",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false,
    "stateTransitionHistory": true
  },
  "authentication": {
    "schemes": [
      "apiKey"
    ]
  },
  "defaultInputModes": [
    "text"
  ],
  "defaultOutputModes": [
    "text"
  ],
  "skills": [
    {
      "id": "get_current_weather",


                                                                                           2

       "name": "Get Current Weather",
       "description": "Retrieve real-time weather for any location.",
       "inputModes": [
         "text"
       ],
       "outputModes": [
         "text"
       ],
       "examples": [
         "What's the weather in Paris?",
         "Current conditions in Tokyo"
       ],
       "tags": [
         "weather",
         "current",
         "real-time"
       ]
     },
     {
       "id": "get_forecast",
       "name": "Get Forecast",
       "description": "Get 5-day weather predictions.",
       "inputModes": [
         "text"
       ],
       "outputModes": [
         "text"
       ],
       "examples": [
         "5-day forecast for New York",
         "Will it rain in London this weekend?"
       ],
       "tags": [
         "weather",
         "forecast",
         "prediction"
       ]
     }
 ]
}



Agent discovery: it allows clients to find Agent Cards, which describe the capabilities
of available A2A Servers. Several strategies exist for this process:

   ●​ Well-Known URI: Agents host their Agent Card at a standardized path (e.g.,

                                                                                      3

      /.well-known/agent.json). This approach offers broad, often automated,
      accessibility for public or domain-specific use.
   ●​ Curated Registries: These provide a centralized catalog where Agent Cards are
      published and can be queried based on specific criteria. This is well-suited for
      enterprise environments needing centralized management and access control.
   ●​ Direct Configuration: Agent Card information is embedded or privately shared.
      This method is appropriate for closely coupled or private systems where dynamic
      discovery isn't crucial.

Regardless of the chosen method, it is important to secure Agent Card endpoints.
This can be achieved through access control, mutual TLS (mTLS), or network
restrictions, especially if the card contains sensitive (though non-secret) information.

Communications and Tasks: In the A2A framework, communication is structured
around asynchronous tasks, which represent the fundamental units of work for
long-running processes. Each task is assigned a unique identifier and moves through
a series of states—such as submitted, working, or completed—a design that supports
parallel processing in complex operations. Communication between agents occurs
through a Message.

This communication contains attributes, which are key-value metadata describing the
message (like its priority or creation time), and one or more parts, which carry the
actual content being delivered, such as plain text, files, or structured JSON data. The
tangible outputs generated by an agent during a task are called artifacts. Like
messages, artifacts are also composed of one or more parts and can be streamed
incrementally as results become available. All communication within the A2A
framework is conducted over HTTP(S) using the JSON-RPC 2.0 protocol for payloads.
To maintain continuity across multiple interactions, a server-generated contextId is
used to group related tasks and preserve context.

Interaction Mechanisms: Request/Response (Polling) Server-Sent Events (SSE). A2A
provides multiple interaction methods to suit a variety of AI application needs, each
with a distinct mechanism:

   ●​ Synchronous Request/Response: For quick, immediate operations. In this
      model, the client sends a request and actively waits for the server to process it
      and return a complete response in a single, synchronous exchange.
   ●​ Asynchronous Polling: Suited for tasks that take longer to process. The client
      sends a request, and the server immediately acknowledges it with a "working"
      status and a task ID. The client is then free to perform other actions and can

                                                                                           4

      periodically poll the server by sending new requests to check the status of the
      task until it is marked as "completed" or "failed."
   ●​ Streaming Updates (Server-Sent Events - SSE): Ideal for receiving real-time,
      incremental results. This method establishes a persistent, one-way connection
      from the server to the client. It allows the remote agent to continuously push
      updates, such as status changes or partial results, without the client needing to
      make multiple requests.
   ●​ Push Notifications (Webhooks): Designed for very long-running or
      resource-intensive tasks where maintaining a constant connection or frequent
      polling is inefficient. The client can register a webhook URL, and the server will
      send an asynchronous notification (a "push") to that URL when the task's
      status changes significantly (e.g., upon completion).

The Agent Card specifies whether an agent supports streaming or push notification
capabilities. Furthermore, A2A is modality-agnostic, meaning it can facilitate these
interaction patterns not just for text, but also for other data types like audio and video,
enabling rich, multimodal AI applications. Both streaming and push notification
capabilities are specified within the Agent Card.

 #Synchronous Request Example
 {
  "jsonrpc": "2.0",
  "id": "1",
  "method": "sendTask",
  "params": {
    "id": "task-001",
    "sessionId": "session-001",
    "message": {
      "role": "user",
      "parts": [
        {
          "type": "text",
          "text": "What is the exchange rate from USD to EUR?"
        }
      ]
    },
    "acceptedOutputModes": ["text/plain"],
    "historyLength": 5
  }
 }




                                                                                          5

The synchronous request uses the sendTask method, where the client asks for and
expects a single, complete answer to its query. In contrast, the streaming request
uses the sendTaskSubscribe method to establish a persistent connection, allowing the
agent to send back multiple, incremental updates or partial results over time.

 # Streaming Request Example
 {
  "jsonrpc": "2.0",
  "id": "2",
  "method": "sendTaskSubscribe",
  "params": {
    "id": "task-002",
    "sessionId": "session-001",
    "message": {
      "role": "user",
      "parts": [
        {
          "type": "text",
          "text": "What's the exchange rate for JPY to GBP today?"
        }
      ]
    },
    "acceptedOutputModes": ["text/plain"],
    "historyLength": 5
  }
 }



Security: Inter-Agent Communication (A2A): Inter-Agent Communication (A2A) is a
vital component of system architecture, enabling secure and seamless data exchange
among agents. It ensures robustness and integrity through several built-in
mechanisms.

Mutual Transport Layer Security (TLS): Encrypted and authenticated connections are
established to prevent unauthorized access and data interception, ensuring secure
communication.

Comprehensive Audit Logs: All inter-agent communications are meticulously
recorded, detailing information flow, involved agents, and actions. This audit trail is
crucial for accountability, troubleshooting, and security analysis.




                                                                                          6

Agent Card Declaration: Authentication requirements are explicitly declared in the
Agent Card, a configuration artifact outlining the agent's identity, capabilities, and
security policies. This centralizes and simplifies authentication management.

Credential Handling: Agents typically authenticate using secure credentials like OAuth
2.0 tokens or API keys, passed via HTTP headers. This method prevents credential
exposure in URLs or message bodies, enhancing overall security.


A2A vs. MCP
A2A is a protocol that complements Anthropic's Model Context Protocol (MCP) (see
Fig. 1). While MCP focuses on structuring context for agents and their interaction with
external data and tools, A2A facilitates coordination and communication among
agents, enabling task delegation and collaboration.




                       Fig.1: Comparison A2A and MCP Protocols

The goal of A2A is to enhance efficiency, reduce integration costs, and foster
innovation and interoperability in the development of complex, multi-agent AI
                                                                                         7

systems. Therefore, a thorough understanding of A2A's core components and
operational methods is essential for its effective design, implementation, and
application in building collaborative and interoperable AI agent systems..


Practical Applications & Use Cases
Inter-Agent Communication is indispensable for building sophisticated AI solutions
across diverse domains, enabling modularity, scalability, and enhanced intelligence.
●​ Multi-Framework Collaboration: A2A's primary use case is enabling
   independent AI agents, regardless of their underlying frameworks (e.g., ADK,
   LangChain, CrewAI), to communicate and collaborate. This is fundamental for
   building complex multi-agent systems where different agents specialize in
   different aspects of a problem.
●​ Automated Workflow Orchestration: In enterprise settings, A2A can facilitate
   complex workflows by enabling agents to delegate and coordinate tasks. For
   instance, an agent might handle initial data collection, then delegate to another
   agent for analysis, and finally to a third for report generation, all communicating
   via the A2A protocol.
●​ Dynamic Information Retrieval: Agents can communicate to retrieve and
   exchange real-time information. A primary agent might request live market data
   from a specialized "data fetching agent," which then uses external APIs to gather
   the information and send it back.



Hands-On Code Example
Let's examine the practical applications of the A2A protocol. The repository at
https://github.com/google-a2a/a2a-samples/tree/main/samples provides examples in
Java, Go, and Python that illustrate how various agent frameworks, such as
LangGraph, CrewAI, Azure AI Foundry, and AG2, can communicate using A2A. All code
in this repository is released under the Apache 2.0 license. To further illustrate A2A's
core concepts, we will review code excerpts focusing on setting up an A2A Server
using an ADK-based agent with Google-authenticated tools. Looking at
https://github.com/google-a2a/a2a-samples/blob/main/samples/python/agents/birthd
ay_planner_adk/calendar_agent/adk_agent.py

import datetime
from google.adk.agents import LlmAgent # type: ignore[import-untyped]
from google.adk.tools.google_api_tool import CalendarToolset # type:

                                                                                         8

 ignore[import-untyped]

 async def create_agent(client_id, client_secret) -> LlmAgent:
    """Constructs the ADK agent."""
    toolset = CalendarToolset(client_id=client_id,
 client_secret=client_secret)
    return LlmAgent(
        model='gemini-2.0-flash-001',
        name='calendar_agent',
        description="An agent that can help manage a user's calendar",
        instruction=f"""
 You are an agent that can help manage a user's calendar.

 Users will request information about the state of their calendar
 or to make changes to their calendar. Use the provided tools for
 interacting with the calendar API.

 If not specified, assume the calendar the user wants is the 'primary'
 calendar.

 When using the Calendar API tools, use well-formed RFC3339
 timestamps.

 Today is {datetime.datetime.now()}.
 """,
