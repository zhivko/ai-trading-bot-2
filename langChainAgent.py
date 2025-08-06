# LangChain agent using locally installed Ollama on Windows (Fixed with agent_scratchpad)

# Updated imports for latest LangChain versions
from langchain_ollama import OllamaLLM
from langchain.agents import create_react_agent, AgentExecutor
from langchain_core.tools import Tool
from langchain_core.prompts import PromptTemplate
from langchain.tools.base import BaseTool
from typing import Any, Dict, Optional, Type
import subprocess
import os

# Initialize the language model with locally installed Ollama
llm = OllamaLLM(
    model="llama3",  # Or any other model you have in Ollama
    base_url="http://localhost:11434",
    temperature=0.1
)

# Create updated tools for the agent to use

# File system tool with proper type annotations
class FileSystemTool(BaseTool):
    name: str = "File System Tool"
    description: str = "Use this tool to interact with the file system. Commands: list_dir, read_file, write_file"
    
    def _run(self, query: str) -> str:
        parts = query.strip().split(" ", 1)
        command = parts[0].lower()
        
        if command == "list_dir":
            path = parts[1] if len(parts) > 1 else "."
            try:
                return str(os.listdir(path))
            except Exception as e:
                return f"Error listing directory: {str(e)}"
                
        elif command == "read_file":
            if len(parts) < 2:
                return "Please provide a file path"
            path = parts[1]
            try:
                if os.path.exists(path):
                    with open(path, "r") as f:
                        return f.read()
                else:
                    return f"File not found: {path}"
            except Exception as e:
                return f"Error reading file: {str(e)}"
                
        elif command == "write_file":
            file_parts = parts[1].split(" ", 1)
            if len(file_parts) < 2:
                return "Please provide a file path and content"
            path, content = file_parts
            try:
                with open(path, "w") as f:
                    f.write(content)
                return f"Successfully wrote to {path}"
            except Exception as e:
                return f"Error writing to file: {str(e)}"
        
        return "Unknown file system command. Available commands: list_dir, read_file, write_file"
    
    async def _arun(self, query: str) -> str:
        # Just a placeholder for async support
        return self._run(query)

# Windows command tool with proper type annotations
class WindowsCommandTool(BaseTool):
    name: str = "Windows Command Tool"
    description: str = "Run simple Windows commands. Use with caution!"
    
    def _run(self, command: str) -> str:
        try:
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True,
                timeout=30
            )
            return f"Exit code: {result.returncode}\nOutput: {result.stdout}\nError: {result.stderr}"
        except Exception as e:
            return f"Error executing command: {str(e)}"
    
    async def _arun(self, command: str) -> str:
        # Just a placeholder for async support
        return self._run(command)

# Knowledge tool function
def get_answer(query: str) -> str:
    # Using LLM directly instead of deprecated LLMChain
    prompt_template = PromptTemplate.from_template(
        "You are a helpful assistant. Answer the following: {query}"
    )
    prompt = prompt_template.format(query=query)
    return llm.invoke(prompt)

# Define tools
tools = [
    Tool(
        name="General Knowledge",
        func=get_answer,
        description="Use this tool for general questions and tasks."
    ),
    FileSystemTool(),
    WindowsCommandTool()
]

# Initialize the agent with the new API - ADDED agent_scratchpad variable
react_prompt_template = """Answer the following questions as best you can. You have access to the following tools:

{tools}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {input}
{agent_scratchpad}"""

# Create a proper PromptTemplate object
react_prompt = PromptTemplate.from_template(react_prompt_template)

# Create the agent
agent = create_react_agent(llm, tools, react_prompt)

# Create the agent executor
agent_executor = AgentExecutor(
    agent=agent, 
    tools=tools, 
    verbose=True,
    handle_parsing_errors=True
)

# Example usage
if __name__ == "__main__":
    print("LangChain Agent with Ollama - Type 'exit' to quit\n")
    print("Available tools:")
    print("1. General Knowledge - Ask questions or get assistance")
    print("2. File System Tool - Commands: list_dir [path], read_file [path], write_file [path] [content]")
    print("3. Windows Command Tool - Run Windows commands (use with caution!)\n")
    
    while True:
        user_input = input("\nAsk something: ")
        if user_input.lower() == "exit":
            break
        try:
            response = agent_executor.invoke({"input": user_input})
            print("\nAgent response:", response["output"])
        except Exception as e:
            print(f"\nError: {str(e)}")