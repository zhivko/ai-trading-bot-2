import requests

def generate_with_lm_studio(prompt, max_tokens=100):
    url = "http://localhost:1234/v1/chat/completions"  # Assuming LM Studio default endpoint
    headers = {
        "Content-Type": "application/json"
    }
    data = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "stream": False
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()
    except requests.RequestException as e:
        return f"Error: {e}"

def generate_code(prompt, max_new_tokens=2000):
    return generate_with_lm_studio(prompt, max_new_tokens)

# Example usage
if __name__ == "__main__":
    print("Qwen Code Generator CLI")
    print("Type your prompt, or 'quit' to exit.")
    while True:
        prompt = input("Prompt: ")
        if prompt.lower() == 'quit':
            break
        result = generate_code(prompt)
        print("Generated Output:")
        print(result)
        print("-" * 50)
