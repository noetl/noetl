import subprocess


def spacy_model():
    try:
        subprocess.check_call(["python", "-m", "spacy", "download", "en_core_web_sm"])
    except subprocess.CalledProcessError:
        print("Error downloading the 'en_core_web_sm' spaCy model.")
        exit(1)


if __name__ == "__main__":
    spacy_model()
