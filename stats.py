class GenerationStatistics:
    def __init__(self, input_time=0, output_time=0, input_tokens=0, output_tokens=0, total_time=0, model_name="llama3-8b-8192"):
        self.input_time = input_time
        self.output_time = output_time
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_time = total_time
        self.model_name = model_name

    def get_input_speed(self):
        return self.input_tokens / self.input_time if self.input_time != 0 else 0
    
    def get_output_speed(self):
        return self.output_tokens / self.output_time if self.output_time != 0 else 0
    
    def add(self, other):
        if not isinstance(other, GenerationStatistics):
            raise TypeError("Can only add GenerationStatistics objects")
        
        self.input_time += other.input_time
        self.output_time += other.output_time
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.total_time += other.total_time

    def __str__(self):
        return (f"## Generation Statistics\n"
                f"- **Model**: {self.model_name}\n"
                f"- **Total Time**: {self.total_time:.2f}s\n"
                f"- **Output Speed**: {self.get_output_speed():.2f} tokens/s\n"
                f"- **Total Tokens**: {self.input_tokens + self.output_tokens}\n")
