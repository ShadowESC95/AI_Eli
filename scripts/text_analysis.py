import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize

# Download necessary NLTK data files
nltk.download('punkt')
nltk.download('stopwords')

def extract_keywords(text, num_keywords=10):
    words = word_tokenize(text.lower())
    filtered_words = [word for word in words if word.isalnum() and word not in 
stopwords.words('english')]
    freq_dist = nltk.FreqDist(filtered_words)
    return freq_dist.most_common(num_keywords)

text = "Your extracted text here"
keywords = extract_keywords(text, num_keywords=10)
print(keywords)  # Print the top keywords
