## What I Built
I built the Prompt Lab by following along with the video lectures in Claude code. I ran each task as a new conversation, using the four different techniques. In some cases, I was fine with the first response but in others I refined it a bit further to get closer to the Wildframe brand.

## Why This Approach
Then explain in at least two sentences why that technique fits the task, pointing to specific features of the task.
Task 1 - Zero Shot
I used Zero Shot because the branding and voice/tone were not important to the task, though I did include the customer profile in the prompt to align perks with customer interest. Since we just needed ideas, examples of voice or tone were not needed so zero shot fit well. 

Task 2 - One Shot
I used One Shot for Task 2 because the branding and tone were relevant but not vital. The format is very repetition and most information is already provided in the label info provided to Claude, so the single sample was sufficient for the task.

Task 3 - Few Shot
I used Few Shot because brand and tone/voice were very important due to the public and customer-facing nature of social media commenting. I used the 3 examples from the Brand Kit but thought Claude's first attempt was too serious, so I iterated to make it warmer and funnier to get similar customer-friendly responses that also stayed on brand.
 
Task 4 - Chain of Thought
I used Chain of Thought here to analyze the available historical data on pop-up locations and reason over it to make a recommendation. It provided the recommendation in the required format. I then asked for its reasoning - just to see, and received the analysis behind the recommendation. 

## Example Run
claude-sonnet-5
You
Wildframe Coffee Roasters is a specialty coffee roaster that sells beans online and through a monthly subscription. Brand voice: warm, plainspoken, and a little irreverent, with no corporate jargon. Customers: environmentally conscious urban professionals. Draft responses to these 3 social media comments:
My order was supposed to arrive Monday. It's Thursday.
Do you make any decaf that doesn't taste like cardboard?
The Huila is my new Sunday morning ritual. Thank you.
Here are some real examples of previous social media interactions - they are good examples of Wildframe's voice.
Comment: Is your packaging actually recyclable, or is that just marketing?
Reply: Fair question. The bag is compostable, the little valve isn't, so pop the valve off first. We're working on that last bit.
Comment: Your Kenya roast tasted burnt to me.
Reply: That's not the cup we were going for. Tell us how you brewed it and we'll help you dial it in, or swap you to something mellower.
Comment: Best coffee I've had in years!!
Reply: This made our whole roasting crew's morning. We'll keep doing the thing.
Comment: Can I pause my subscription while I travel?
Reply: Yep. Account, then Subscription, then Pause. Your beans will wait for you, mostly patiently.
Give the three draft comments replies in list format, numbered 1 through 3, each no more than 40 words, with no emojis.
Claude
That's three days too late and we're sorry. Send us your order number and we'll track it down (or replace it outright, no fuss).
We hear you, most decaf is sad. Try our Swiss Water decaf, it's got real flavor, not just the absence of caffeine.
Okay, this is exactly why we roast. Enjoy your Sundays, Huila's got your back.
You
Make them slightly warmer and funnier.
Claude
Thursday is not Monday, we know. Your coffee is apparently taking the scenic route. Send us the order number and we'll hunt it down like it owes us money.
We hear you, most decaf tastes like a sad apology. Try our Swiss Water decaf, it's got actual personality, not just the caffeine missing.
This is the kind of message that makes us weirdly emotional over coffee beans. Huila says hi back. Enjoy your Sundays, you've earned them.

## Reflection
Even though I needed to iterate on Task 3, I think the few shot technique was best. The more information Claude has available to answer a question, the better and more thorough and accurate output you will get.
That said, the technique used has to correspond to the task. Few shot wouldn't necessarily work for Task 4 well - or you could have used Few Shot on Task 1, but its far more information in the prompt that is needed for Task 1 to get a usable outcome from Claude. One shot did okay for Task 2, but I think additional info in a few shot prompt could have helped with the voice a bit.