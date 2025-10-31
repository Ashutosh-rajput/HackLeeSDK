import subprocess
import os
import tempfile
import logging
from pathlib import Path


def compile_java_code(code: str):
    """
    Compiles Java code and returns compilation errors if any.
    Returns None if compilation is successful, error message if failed.
    """
    class_name = "Main"
    file_name = f"{class_name}.java"

    try:
        # Write Java code to a file
        with open(file_name, 'w') as writer:
            writer.write(code)

        # Compile the Java file using javac
        result = subprocess.run(
            ['javac', file_name],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            return result.stderr

        return None

    except FileNotFoundError:
        return "Java compiler (javac) not found. Please ensure Java JDK is installed and in PATH."
    except Exception as e:
        return f"Compilation error: {str(e)}"
    finally:
        # Clean up the .java file
        if os.path.exists(file_name):
            try:
                os.remove(file_name)
            except:
                pass


def run_java_class(input_data: str):
    """
    Executes compiled Java class with input and captures output.
    Returns the output as a string.
    """
    try:
        # Execute the Java class
        process = subprocess.Popen(
            ['java', 'Main'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # Provide input and capture output
        stdout, stderr = process.communicate(input=input_data)

        if process.returncode != 0:
            # Handle different types of Java exceptions
            if "InputMismatchException" in stderr:
                logging.error("InputMismatchException - The input is of an incorrect type.")
                raise ValueError("The input is of an incorrect type.")
            elif "NoSuchElementException" in stderr:
                logging.error("NoSuchElementException - Scanner tried to read but no input was provided.")
                raise EOFError("Scanner tried to read but no input was provided.")
            elif "NullPointerException" in stderr:
                logging.error("NullPointerException - A null object was accessed in the executed code.")
                raise AttributeError("A null object was accessed in the executed code.")
            else:
                logging.error(f"Unexpected exception occurred: {stderr}")
                raise Exception(f"Error in execution: {stderr}")

        return stdout

    except FileNotFoundError:
        return "Java runtime (java) not found. Please ensure Java is installed and in PATH."
    except Exception as e:
        logging.error(f"Execution error: {str(e)}")
        raise


def compile_and_run_java(code:str, input_data:str):
    """
    Method that compiles and runs Java code.
    """
    # Compile the code
    compilation_error = compile_java_code(code)
    if compilation_error:
        return f"Compilation failed:\n{compilation_error}"

    # Run the compiled class
    try:
        output = run_java_class(input_data)
        return output
    except Exception as e:
        return f"Execution failed: {str(e)}"


