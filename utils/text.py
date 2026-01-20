import tiktoken
def get_tokenizer(model:str):
    try:
        encoding = tiktoken.encoding_for_model(model)
        return encoding.encode
    except Exception:
        encoding= tiktoken.get_encoding('cl10k_base') # the arg is called as 'base' and this is used by gpt4
        return encoding.encode
    

def count_token(text:str, model:str) -> int:
    tokenizer = get_tokenizer(model)
    if tokenizer:
        return len(tokenizer(text))
    
    return estimate_tokens(text)

def estimate_tokens(text:str) -> int:
    return max(1,len(text) // 4) # esitmated this math from https://platform.openai.com/tokenizer - 4 chars = 1 token