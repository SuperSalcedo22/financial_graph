import configparser
import os
import logging
import time
import sys
import pandas as pd
from decimal import Decimal, ROUND_HALF_UP
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import threading

def create_logger(script_dir):
    '''Creates the logger object for the script which writes to the console and a file that has the date as an extension to it'''

    # make sure the logger is global
    global logger

    # get the current date
    date_string = time.strftime("%Y-%m-%d", time.localtime())

    # Create the log file name in the same directory as the script, with the filedate to differentiate
    filename = os.path.join(script_dir,f"Graph_logger_{date_string}.log")

    # create the log object and set its level
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG) 

    # create 2 handlers
    # filehandler writes to the log file and will have all messages
    file_handler = logging.FileHandler(filename)
    file_handler.setLevel(logging.DEBUG)
    # consoler handler prints to console but only shows info and above
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # create the general format for both loggers
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    
    # Set the formatter for both
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # Add the handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

def validate_config(script_dir):
    '''Check the config file exists and then check the parameters are correct'''
    
    # get the path for the config file
    config_path=os.path.join(script_dir,"graph_values.ini")

    # create the config object and check the config file exists
    config=configparser.ConfigParser()
    if not os.path.exists(config_path):
        logger.error(f"{config_path} is missing")
        raise FileNotFoundError("Missing file")
    # check that the config file has the values header
    config.read(config_path)
    for section in ["Values"]:
        if section not in config.sections():
            logger.error(f"Missing section: {section}")
            raise ValueError(f"Missing section: {section}")
        logger.debug(f"Config file contains {section}")
        # Check for missing keys in each section
        for key in ["name","age","maximum_age","pension_fund_value","annual_income","pct_growth_above_inflation","pct_charges_above_inflation"]:
            logger.debug(f"{section} contains {key}")
            if key not in config[section]:
                logger.error(f"{key} missing from {section}")
                raise ValueError(f"{key} missing from {section}")
    logger.info("Config file is valid")

    return config

# Helper function to convert values to Decimal and round them
def to_decimal_round(value, decimal_places=20):
    '''Convert input value into precise x decimal places - default 20 for more precision'''
    if pd.isna(value):
        logger.error(f"Cant convert {value} to decimal")
        return value  # Return NaN or None as is
    logger.debug(f"Converting {value} to {decimal_places} dp")
    return Decimal(value).quantize(Decimal('1.{}'.format('0' * decimal_places)), rounding=ROUND_HALF_UP)

class AMR_Graph():

    def __init__(self,config,script_dir):

        self.script_dir=script_dir
        
        # convert all the value into numerical values
        for key, value in config['Values'].items():
            # remove any commas from the string
            value=value.replace(",","")

            # make the value an integer or a float depending on the decimal point
            try:
                if '.' in value:
                    value=to_decimal_round(value)
                else:
                    value=int(value)
            except ValueError:
                # actual strings will stay as strings
                pass
            
            # Use setattr to dynamically assign the attributes
            setattr(self, key, value)

        # change the percent values into actual percentages
        self.pct_growth_above_inflation = self.pct_growth_above_inflation/100
        self.pct_charges_above_inflation = self.pct_charges_above_inflation/100

    def create_dataframe(self):
        '''Create the dataframe that will have all the data'''

        # create the temp values to be used in the first row
        initial_growth_value=to_decimal_round(self.pension_fund_value*self.pct_growth_above_inflation)
        initial_charge_value=to_decimal_round(self.pension_fund_value*self.pct_charges_above_inflation)

        # create the first row and create the dataframe
        data = {
            'Age': [self.age],
            'pension_fund_value': [to_decimal_round(self.pension_fund_value)],
            'projected_growth': [initial_growth_value],
            'charges':[initial_charge_value],
            'ending_fund_value': [self.pension_fund_value+initial_growth_value-self.annual_income-initial_charge_value]
        }
        df = pd.DataFrame(data)
        logger.debug(f"Inital dataframe made {df}")

        # get the number of rows for use in the dataframe
        no_rows=self.maximum_age-self.age
        logger.debug(f"{no_rows} being added to dataframe")

        # use a loop to calculate the new rows and add them to the dataframe
        for i in range(no_rows):

            # final fund value from the previous row and use that to calculate the values for the row
            previous_end_fund_value = df.iloc[-1]['ending_fund_value']
            projected_growth=to_decimal_round(previous_end_fund_value*self.pct_growth_above_inflation)
            projected_charge=to_decimal_round(previous_end_fund_value*self.pct_charges_above_inflation)
            
            # Create the new row from the values
            new_row = [
                        self.age+i+1, 
                       previous_end_fund_value,
                       projected_growth,
                       projected_charge,
                       previous_end_fund_value+projected_growth-self.annual_income-projected_charge
                    ]
            
            # Append the new row to the DataFrame
            df.loc[len(df.index)] = new_row
        logger.info(f"All new rows added to dataframe")
        # with all the calculations done, change the accuracy of the datframe to be 2 dp to match finance using a lambda function
        df = df.apply(lambda col: col.apply(lambda value: Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if pd.notna(value) else value))
        logger.debug("All columns rounded to 2 dp")

        # make sure the age column is an integer
        df['Age'] = df['Age'].astype(int)
        logger.debug("Age converted to integer")

        # now output the dataframe into a csv using the client name
        csv_path=os.path.join(self.script_dir,f"{self.name}_values.csv")
        df.to_csv(csv_path, index=False)
        logger.debug(f"Csv written to {csv_path}")

        # filter the dataframe by changing all ending fund values less than 0 to 0
        df.loc[df['ending_fund_value'] < 0, 'ending_fund_value'] = 0
        logger.debug("Values below 0 filtered from dataframe")
        
        # return the dataframe to be used in creating the graphs
        return df
    
    def create_graph(self,df):
        '''Using the input dataframe, create the graph and save it'''

        # create the figure (width by height in inches)
        plt.figure(figsize=(12, 8))  
        # create the bar chart
        plt.bar(df['Age'].astype(str), df['ending_fund_value'])
        logger.debug("Graph created")

        # Add titles and labels
        plt.title('Fund value by age')
        plt.xlabel('Age')
        plt.ylabel('Fund Value')
        logger.debug("Axis added")

        # Apply currency formatting using a lambda function
        plt.gca().yaxis.set_major_formatter(FuncFormatter(lambda x, _: f'£{x:,.2f}'))
        logger.debug("Currency settings added to y axis")

        # Save the plot to a png 
        image_path=os.path.join(f'{self.name}_chart.png')
        plt.savefig(image_path)
        logger.debug(f"PNG saved to {image_path}")

        # Close the plot to free up memory
        plt.close()

    def main(self):
        '''Run the objects processing'''

        # create the dataframe 
        df=self.create_dataframe()

        # create the bar chart
        self.create_graph(df)
            
def exit_after_5_mins():
    '''Exit the scipt after 5 minutes regardless'''
    
    time.sleep(300)
    logger.error("Took longer than 5 minutes, please investigate")

    # force all threads close
    os._exit(1)

# create the nonetype object that is global
logger = None

if __name__=='__main__':
    
    # start the 5 minute timer whilst the other processes run
    timer = threading.Thread(target=exit_after_5_mins)
    timer.daemon = True  # Set the thread as a daemon - so it stops when the script is finished
    timer.start()

    # current directory for the script to be used for other functions
    script_dir = os.getcwd()

    # create the logger 
    logger=create_logger(script_dir)

    # validate the config and then create the object
    config=validate_config(script_dir)
    obj=AMR_Graph(config,script_dir)
    logger.debug(f"Object initialised with {vars(obj)} values")

    # run the script
    obj.main()
    logger.info("Script ran with no errors")
    sys.exit(0)