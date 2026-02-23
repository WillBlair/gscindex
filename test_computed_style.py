from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time

options = Options()
options.add_argument('--headless')
driver = webdriver.Chrome(options=options)
driver.get("http://localhost:8050/docs")
time.sleep(2)
h4 = driver.find_element(By.CSS_SELECTOR, ".p-card h4")
print("font-size:", h4.value_of_css_property("font-size"))
print("color:", h4.value_of_css_property("color"))
print("text-transform:", h4.value_of_css_property("text-transform"))
print("font-weight:", h4.value_of_css_property("font-weight"))
driver.quit()
