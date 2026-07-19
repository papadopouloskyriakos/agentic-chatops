# Appendix B: AI Agentic Interactions — From GUI to Real-World Environment

> From *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems* by Antonio Gulli.
> Source: [`docs/Agentic_Design_Patterns.pdf`](../Agentic_Design_Patterns.pdf) (extracted 2026-04-23 via `pdftotext -layout`).
> Overview: [`docs/gulli-book-overview.md`](../gulli-book-overview.md).
> Our platform's status on this pattern: see [`wiki/patterns/`](../../wiki/patterns/).

---


Iterative Prompting / Refinement
This technique involves starting with a simple, basic prompt and then iteratively
refining it based on the model's initial responses. If the model's output isn't quite
right, you analyze the shortcomings and modify the prompt to address them. This is
less about an automated process (like APE) and more about a human-driven iterative
design loop.
●​ Example:
   ○​ Attempt 1: "Write a product description for a new type of coffee maker."
       (Result is too generic).
    ○​ Attempt 2: "Write a product description for a new type of coffee maker.
       Highlight its speed and ease of cleaning." (Result is better, but lacks detail).

                                                                                          19

    ○​ Attempt 3: "Write a product description for the 'SpeedClean Coffee Pro'.
        Emphasize its ability to brew a pot in under 2 minutes and its self-cleaning
        cycle. Target busy professionals." (Result is much closer to desired).

Providing Negative Examples
While the principle of "Instructions over Constraints" generally holds true, there are
situations where providing negative examples can be helpful, albeit used carefully. A
negative example shows the model an input and an undesired output, or an input and
an output that should not be generated. This can help clarify boundaries or prevent
specific types of incorrect responses.
 ●​ Example:​
    Generate a list of popular tourist attractions in Paris. Do NOT include the Eiffel
    Tower.​
    ​
    Example of what NOT to do:​
    Input: List popular landmarks in Paris.​
    Output: The Eiffel Tower, The Louvre, Notre Dame Cathedral.

Using Analogies
Framing a task using an analogy can sometimes help the model understand the
desired output or process by relating it to something familiar. This can be particularly
useful for creative tasks or explaining complex roles.
 ●​ Example:​
    Act as a "data chef". Take the raw ingredients (data points) and prepare a
    "summary dish" (report) that highlights the key flavors (trends) for a business
    audience.

Factored Cognition / Decomposition
For very complex tasks, it can be effective to break down the overall goal into smaller,
more manageable sub-tasks and prompt the model separately on each sub-task. The
results from the sub-tasks are then combined to achieve the final outcome. This is
related to prompt chaining and planning but emphasizes the deliberate
decomposition of the problem.
 ●​ Example: To write a research paper:
    ○​ Prompt 1: "Generate a detailed outline for a paper on the impact of AI on the
       job market."
    ○​ Prompt 2: "Write the introduction section based on this outline: [insert outline
       intro]."
                                                                                         20

    ○​ Prompt 3: "Write the section on 'Impact on White-Collar Jobs' based on this
       outline: [insert outline section]." (Repeat for other sections).
    ○​ Prompt N: "Combine these sections and write a conclusion."

Retrieval Augmented Generation (RAG)
RAG is a powerful technique that enhances language models by giving them access to
external, up-to-date, or domain-specific information during the prompting process.
When a user asks a question, the system first retrieves relevant documents or data
from a knowledge base (e.g., a database, a set of documents, the web). This retrieved
information is then included in the prompt as context, allowing the language model to
generate a response grounded in that external knowledge. This mitigates issues like
hallucination and provides access to information the model wasn't trained on or that is
very recent. This is a key pattern for agentic systems that need to work with dynamic
or proprietary information.
●​ Example:
   ○​ User Query: "What are the new features in the latest version of the Python
       library 'X'?"
    ○​ System Action: Search a documentation database for "Python library X latest
       features".
    ○​ Prompt to LLM: "Based on the following documentation snippets: [insert
       retrieved text], explain the new features in the latest version of Python library
       'X'."

Persona Pattern (User Persona):
While role prompting assigns a persona to the model, the Persona Pattern involves
describing the user or the target audience for the model's output. This helps the
model tailor its response in terms of language, complexity, tone, and the kind of
information it provides.
●​ Example:​
    You are explaining quantum physics. The target audience is a high school student
    with no prior knowledge of the subject. Explain it simply and use analogies they
    might understand.​
    ​
    Explain quantum physics: [Insert basic explanation request]​




                                                                                       21

These advanced and supplementary techniques provide further tools for prompt
engineers to optimize model behavior, integrate external information, and tailor
interactions for specific users and tasks within agentic workflows.


Using Google Gems
Google's AI "Gems" (see Fig. 1) represent a user-configurable feature within its large
language model architecture. Each "Gem" functions as a specialized instance of the
core Gemini AI, tailored for specific, repeatable tasks. Users create a Gem by
providing it with a set of explicit instructions, which establishes its operational
parameters. This initial instruction set defines the Gem's designated purpose,
response style, and knowledge domain. The underlying model is designed to
consistently adhere to these pre-defined directives throughout a conversation.

This allows for the creation of highly specialized AI agents for focused applications.
For example, a Gem can be configured to function as a code interpreter that only
references specific programming libraries. Another could be instructed to analyze
data sets, generating summaries without speculative commentary. A different Gem
might serve as a translator adhering to a particular formal style guide. This process
creates a persistent, task-specific context for the artificial intelligence.

Consequently, the user avoids the need to re-establish the same contextual
information with each new query. This methodology reduces conversational
redundancy and improves the efficiency of task execution. The resulting interactions
are more focused, yielding outputs that are consistently aligned with the user's initial
requirements. This framework allows for applying fine-grained, persistent user
direction to a generalist AI model. Ultimately, Gems enable a shift from
general-purpose interaction to specialized, pre-defined AI functionalities.




                                                                                         22

                          Fig.1: Example of Google Gem usage.



Using LLMs to Refine Prompts (The Meta Approach)
We've explored numerous techniques for crafting effective prompts, emphasizing
clarity, structure, and providing context or examples. This process, however, can be
iterative and sometimes challenging. What if we could leverage the very power of
large language models, like Gemini, to help us improve our prompts? This is the
essence of using LLMs for prompt refinement – a "meta" application where AI assists
in optimizing the instructions given to AI.

This capability is particularly "cool" because it represents a form of AI
self-improvement or at least AI-assisted human improvement in interacting with AI.
Instead of solely relying on human intuition and trial-and-error, we can tap into the
LLM's understanding of language, patterns, and even common prompting pitfalls to


                                                                                        23

get suggestions for making our prompts better. It turns the LLM into a collaborative
partner in the prompt engineering process.

How does this work in practice? You can provide a language model with an existing
prompt that you're trying to improve, along with the task you want it to accomplish
and perhaps even examples of the output you're currently getting (and why it's not
meeting your expectations). You then prompt the LLM to analyze the prompt and
suggest improvements.

A model like Gemini, with its strong reasoning and language generation capabilities,
can analyze your existing prompt for potential areas of ambiguity, lack of specificity,
or inefficient phrasing. It can suggest incorporating techniques we've discussed, such
as adding delimiters, clarifying the desired output format, suggesting a more effective
persona, or recommending the inclusion of few-shot examples.

The benefits of this meta-prompting approach include:
●​ Accelerated Iteration: Get suggestions for improvement much faster than pure
   manual trial and error.
●​ Identification of Blind Spots: An LLM might spot ambiguities or potential
   misinterpretations in your prompt that you overlooked.
●​ Learning Opportunity: By seeing the types of suggestions the LLM makes, you
   can learn more about what makes prompts effective and improve your own
   prompt engineering skills.
●​ Scalability: Potentially automate parts of the prompt optimization process,
   especially when dealing with a large number of prompts.
It's important to note that the LLM's suggestions are not always perfect and should be
evaluated and tested, just like any manually engineered prompt. However, it provides a
powerful starting point and can significantly streamline the refinement process.
●​ Example Prompt for Refinement:​
    Analyze the following prompt for a language model and suggest ways to improve
    it to consistently extract the main topic and key entities (people, organizations,
    locations) from news articles. The current prompt sometimes misses entities or
    gets the main topic wrong.​
    ​
    Existing Prompt:​
    "Summarize the main points and list important names and places from this article:
    [insert article text]"​
    ​


                                                                                       24

    Suggestions for Improvement:​


In this example, we're using the LLM to critique and enhance another prompt. This
meta-level interaction demonstrates the flexibility and power of these models,
allowing us to build more effective agentic systems by first optimizing the fundamental
instructions they receive. It's a fascinating loop where AI helps us talk better to AI.


Prompting for Specific Tasks
While the techniques discussed so far are broadly applicable, some tasks benefit from
specific prompting considerations. These are particularly relevant in the realm of code
and multimodal inputs.


Code Prompting
Language models, especially those trained on large code datasets, can be powerful
assistants for developers. Prompting for code involves using LLMs to generate,
explain, translate, or debug code. Various use cases exist:
●​ Prompts for writing code: Asking the model to generate code snippets or
   functions based on a description of the desired functionality.
    ○​ Example: "Write a Python function that takes a list of numbers and returns
       the average."
●​ Prompts for explaining code: Providing a code snippet and asking the model to
   explain what it does, line by line or in a summary.
    ○​ Example: "Explain the following JavaScript code snippet: [insert code]."
●​ Prompts for translating code: Asking the model to translate code from one
   programming language to another.
    ○​ Example: "Translate the following Java code to C++: [insert code]."
●​ Prompts for debugging and reviewing code: Providing code that has an error
   or could be improved and asking the model to identify issues, suggest fixes, or
   provide refactoring suggestions.
    ○​ Example: "The following Python code is giving a 'NameError'. What is wrong
       and how can I fix it? [insert code and traceback]."
Effective code prompting often requires providing sufficient context, specifying the
desired language and version, and being clear about the functionality or issue.




                                                                                       25

Multimodal Prompting
While the focus of this appendix and much of current LLM interaction is text-based,
the field is rapidly moving towards multimodal models that can process and generate
information across different modalities (text, images, audio, video, etc.). Multimodal
prompting involves using a combination of inputs to guide the model. This refers to
using multiple input formats instead of just text.
●​ Example: Providing an image of a diagram and asking the model to explain the
    process shown in the diagram (Image Input + Text Prompt). Or providing an image
    and asking the model to generate a descriptive caption (Image Input + Text
    Prompt -> Text Output).
As multimodal capabilities become more sophisticated, prompting techniques will
evolve to effectively leverage these combined inputs and outputs.


Best Practices and Experimentation
Becoming a skilled prompt engineer is an iterative process that involves continuous
learning and experimentation. Several valuable best practices are worth reiterating
and emphasizing:
●​ Provide Examples: Providing one or few-shot examples is one of the most
   effective ways to guide the model.
●​ Design with Simplicity: Keep your prompts concise, clear, and easy to
   understand. Avoid unnecessary jargon or overly complex phrasing.
●​ Be Specific about the Output: Clearly define the desired format, length, style,
   and content of the model's response.
●​ Use Instructions over Constraints: Focus on telling the model what you want it
   to do rather than what you don't want it to do.
●​ Control the Max Token Length: Use model configurations or explicit prompt
   instructions to manage the length of the generated output.
●​ Use Variables in Prompts: For prompts used in applications, use variables to
   make them dynamic and reusable, avoiding hardcoding specific values.
●​ Experiment with Input Formats and Writing Styles: Try different ways of
   phrasing your prompt (question, statement, instruction) and experiment with
   different tones or styles to see what yields the best results.
●​ For Few-Shot Prompting with Classification Tasks, Mix Up the Classes:
