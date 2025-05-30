import os
import re
import json
import arxiv
import yaml
import logging
import argparse
import datetime
import requests
import time
from dateutil.relativedelta import relativedelta

logging.basicConfig(format='[%(asctime)s %(levelname)s] %(message)s',
                    datefmt='%m/%d/%Y %H:%M:%S',
                    level=logging.INFO)

base_url = "https://arxiv.paperswithcode.com/api/v0/papers/"
github_url = "https://api.github.com/search/repositories"
arxiv_url = "http://arxiv.org/"

def load_config(config_file: str) -> dict:
    '''
    config_file: input config file path
    return: a dict of configuration
    '''
    # make filters pretty
    def pretty_filters(**config) -> dict:
        keywords = dict()
        EXCAPE = '\"'
        QUOTA = '' # NO-USE
        OR = ' OR ' # Updated for better readability
        def parse_filters(filters: list):
            ret = ''
            for idx in range(0, len(filters)):
                filter = filters[idx]
                if len(filter.split()) > 1:
                    ret += (EXCAPE + filter + EXCAPE)  
                else:
                    ret += (QUOTA + filter + QUOTA)   
                if idx != len(filters) - 1:
                    ret += OR
            return ret
        for k, v in config['keywords'].items():
            keywords[k] = parse_filters(v['filters'])
        return keywords
    
    with open(config_file, 'r') as f:
        config = yaml.load(f, Loader=yaml.FullLoader) 
        config['kv'] = pretty_filters(**config)
        logging.info(f'config = {config}')
    return config 

def get_authors(authors):
    """
    Concatenate all author names with a comma.
    """
    return ", ".join(author.name for author in authors)

def sort_papers(papers):
    output = dict()
    keys = list(papers.keys())
    keys.sort(reverse=True)
    for key in keys:
        output[key] = papers[key]
    return output    

def get_daily_papers(topic, query="symplectic geometry", max_results=50, start_date=None, end_date=None):
    """
    @param topic: str
    @param query: str
    @param max_results: int
    @param start_date: datetime.date or None
    @param end_date: datetime.date or None
    @return paper_with_code: dict
    """
    content = dict() 
    content_to_web = dict()
    
    # Enhanced search for symplectic geometry with categories
    categories = "cat:math.SG OR cat:math.DG OR cat:math.AG OR cat:math-ph OR cat:math.QA"
    enhanced_query = f"({query}) AND ({categories})"
    
    # Add date filter if specified
    if start_date and end_date:
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")
        enhanced_query += f" AND submittedDate:[{start_str} TO {end_str}]"
        logging.info(f"Searching from {start_date} to {end_date}")
    
    search_engine = arxiv.Search(
        query=enhanced_query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending
    )

    for result in search_engine.results():
        paper_id = result.get_short_id()
        paper_title = result.title
        paper_url = result.entry_id
        code_url = base_url + paper_id
        paper_abstract = result.summary.replace("\n", " ")
        paper_authors = get_authors(result.authors)
        primary_category = result.primary_category
        publish_time = result.published.date()
        update_time = result.updated.date()
        comments = result.comment

        logging.info(f"Time = {update_time} title = {paper_title[:50]}... author = {paper_authors[:30]}...")

        ver_pos = paper_id.find('v')
        if ver_pos == -1:
            paper_key = paper_id
        else:
            paper_key = paper_id[0:ver_pos]    
        paper_url = arxiv_url + 'abs/' + paper_key
        
        try:
            r = requests.get(code_url).json()
            repo_url = None
            if "official" in r and r["official"]:
                repo_url = r["official"]["url"]
            
            if repo_url is not None:
                content[paper_key] = "|**{}**|**{}**|{}|[{}]({})|**[link]({})**|\n".format(
                       update_time, paper_title, paper_authors, paper_key, paper_url, repo_url)
                content_to_web[paper_key] = "- {}, **{}**, {}, Paper: [{}]({}), Code: **[{}]({})**".format(
                       update_time, paper_title, paper_authors, paper_url, paper_url, repo_url, repo_url)
            else:
                content[paper_key] = "|**{}**|**{}**|{}|[{}]({})|null|\n".format(
                       update_time, paper_title, paper_authors, paper_key, paper_url)
                content_to_web[paper_key] = "- {}, **{}**, {}, Paper: [{}]({})".format(
                       update_time, paper_title, paper_authors, paper_url, paper_url)

            if comments is not None:
                content_to_web[paper_key] += f", {comments}\n"
            else:
                content_to_web[paper_key] += f"\n"

        except Exception as e:
            logging.error(f"exception: {e} with id: {paper_key}")

    data = {topic: content}
    data_web = {topic: content_to_web}
    return data, data_web 

def get_historical_papers(topic, query, start_year=1990, end_year=None, max_per_year=500):
    """
    Collect all papers from start_year to end_year
    @param topic: str
    @param query: str  
    @param start_year: int
    @param end_year: int or None (defaults to current year)
    @param max_per_year: int
    @return: dict, dict
    """
    if end_year is None:
        end_year = datetime.datetime.now().year
    
    all_content = dict()
    all_content_web = dict()
    
    logging.info(f"Starting historical collection from {start_year} to {end_year}")
    
    for year in range(start_year, end_year + 1):
        logging.info(f"Processing year {year}...")
        
        # Define date range for the year
        start_date = datetime.date(year, 1, 1)
        end_date = datetime.date(year, 12, 31)
        
        try:
            data, data_web = get_daily_papers(
                topic=topic, 
                query=query, 
                max_results=max_per_year,
                start_date=start_date,
                end_date=end_date
            )
            
            # Merge results
            for topic_key in data:
                if topic_key in all_content:
                    all_content[topic_key].update(data[topic_key])
                    all_content_web[topic_key].update(data_web[topic_key])
                else:
                    all_content[topic_key] = data[topic_key]
                    all_content_web[topic_key] = data_web[topic_key]
            
            logging.info(f"Year {year} completed. Found {len(data[topic])} papers.")
            
            # Add delay to respect arXiv rate limits
            time.sleep(3)
            
        except Exception as e:
            logging.error(f"Error processing year {year}: {e}")
            # Continue with next year
            continue
    
    total_papers = sum(len(content) for content in all_content.values())
    logging.info(f"Historical collection completed. Total papers: {total_papers}")
    
    return all_content, all_content_web

def update_paper_links(json_file):
    """
    Update paper links in existing JSON file
    """
    logging.info("Updating paper links...")
    
    with open(json_file, "r") as f:
        content = f.read()
        if not content:
            data = {}
        else:
            data = json.loads(content)
    
    # For each paper, verify and update links
    for topic in data:
        for paper_id in data[topic]:
            try:
                # Reconstruct arXiv URL
                clean_id = paper_id.split('v')[0] if 'v' in paper_id else paper_id
                new_url = f"{arxiv_url}abs/{clean_id}"
                
                # Test if URL is accessible
                response = requests.head(new_url, timeout=5)
                if response.status_code == 200:
                    # Update the entry with new URL
                    entry = data[topic][paper_id]
                    if isinstance(entry, str):
                        # Update URL in the markdown format
                        data[topic][paper_id] = re.sub(
                            r'\[([^\]]+)\]\([^)]+\)',
                            f'[{clean_id}]({new_url})',
                            entry
                        )
                
            except Exception as e:
                logging.warning(f"Could not update link for {paper_id}: {e}")
    
    # Save updated data
    with open(json_file, "w") as f:
        json.dump(data, f, indent=2)
    
    logging.info("Paper links updated")

def update_json_file(filename, data_dict):
    '''
    daily update json file using data_dict
    '''
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else '.', exist_ok=True)
    
    # Load existing data
    if os.path.exists(filename):
        with open(filename, "r") as f:
            content = f.read()
            if not content:
                m = {}
            else:
                m = json.loads(content)
    else:
        m = {}
            
    json_data = m.copy() 
    
    # update papers in each keywords         
    for data in data_dict:
        for keyword in data.keys():
            papers = data[keyword]

            if keyword in json_data.keys():
                json_data[keyword].update(papers)
            else:
                json_data[keyword] = papers

    with open(filename, "w") as f:
        json.dump(json_data, f, indent=2)
    
def json_to_md(filename, md_filename,
               task='',
               to_web=True, 
               use_title=True, 
               use_tc=True,
               show_badge=False,
               use_b2t=True):
    """
    @param filename: str
    @param md_filename: str
    @return None
    """
    def pretty_math(s: str) -> str:
        ret = ''
        match = re.search(r"\$.*\$", s)
        if match == None:
            return s
        math_start, math_end = match.span()
        space_trail = space_leading = ''
        if s[:math_start][-1] != ' ' and '*' != s[:math_start][-1]: 
            space_trail = ' ' 
        if s[math_end:][0] != ' ' and '*' != s[math_end:][0]: 
            space_leading = ' ' 
        ret += s[:math_start] 
        ret += f'{space_trail}${match.group()[1:-1].strip()}${space_leading}' 
        ret += s[math_end:]
        return ret
  
    DateNow = datetime.date.today()
    DateNow = str(DateNow)
    DateNow = DateNow.replace('-', '.')
    
    with open(filename, "r") as f:
        content = f.read()
        if not content:
            data = {}
        else:
            data = json.loads(content)

    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(md_filename) if os.path.dirname(md_filename) else '.', exist_ok=True)

    with open(md_filename, "w+") as f:
        pass

    with open(md_filename, "a+") as f:
        if (use_title == True) and (to_web == True):
            f.write("---\n" + "layout: default\n" + "---\n\n")
        
        if show_badge == True:
            f.write(f"[![Contributors][contributors-shield]][contributors-url]\n")
            f.write(f"[![Forks][forks-shield]][forks-url]\n")
            f.write(f"[![Stargazers][stars-shield]][stars-url]\n")
            f.write(f"[![Issues][issues-shield]][issues-url]\n\n")    
                
        # Updated title for symplectic geometry
        if use_title == True:
            f.write("# Collection of Articles on Symplectic Geometry\n\n")
            f.write("> Automatically updated on " + DateNow + "\n")
        else:
            f.write("> Automatically updated on " + DateNow + "\n")

        f.write("\n")

        if use_tc == True:
            f.write("<details>\n")
            f.write("  <summary>Table of Contents</summary>\n")
            f.write("  <ol>\n")
            for keyword in data.keys():
                day_content = data[keyword]
                if not day_content:
                    continue
                kw = keyword.replace(' ', '-').replace(',', '').replace('(', '').replace(')', '')
                f.write(f"    <li><a href=#{kw.lower()}>{keyword}</a></li>\n")
            f.write("  </ol>\n")
            f.write("</details>\n\n")
        
        for keyword in data.keys():
            day_content = data[keyword]
            if not day_content:
                continue

            f.write(f"## {keyword}\n\n")

            if use_title == True:
                if to_web == False:
                    f.write("|Publish Date|Title|Authors|PDF|Code|\n" + "|---|---|---|---|---|\n")
                else:
                    f.write("| Publish Date | Title | Authors | PDF | Code |\n")
                    f.write("|:---------|:-----------------------|:---------|:------|:------|\n")

            day_content = sort_papers(day_content)
        
            for _, v in day_content.items():
                if v is not None:
                    f.write(pretty_math(v)) 

            f.write(f"\n")
            
            if use_b2t:
                top_info = f"#Updated on {DateNow}"
                top_info = top_info.replace(' ', '-').replace('.', '')
                f.write(f"<p align=right>(<a href={top_info.lower()}>back to top</a>)</p>\n\n")
        
        # Add footer with your name
        f.write("\n---\n\n")
        f.write("*Created by Yassine Ait Mohamed*\n\n")
        f.write("This collection is automatically updated using arXiv API to track the latest research in symplectic geometry and related fields.\n")
            
        if show_badge == True:
            # Updated badge URLs for your repo
            f.write((f"[contributors-shield]: https://img.shields.io/github/"
                     f"contributors/YassineAitMohamed/symplectic-arxiv-daily.svg?style=for-the-badge\n"))
            f.write((f"[contributors-url]: https://github.com/YassineAitMohamed/"
                     f"symplectic-arxiv-daily/graphs/contributors\n"))
            f.write((f"[forks-shield]: https://img.shields.io/github/forks/YassineAitMohamed/"
                     f"symplectic-arxiv-daily.svg?style=for-the-badge\n"))
            f.write((f"[forks-url]: https://github.com/YassineAitMohamed/"
                     f"symplectic-arxiv-daily/network/members\n"))
            f.write((f"[stars-shield]: https://img.shields.io/github/stars/YassineAitMohamed/"
                     f"symplectic-arxiv-daily.svg?style=for-the-badge\n"))
            f.write((f"[stars-url]: https://github.com/YassineAitMohamed/"
                     f"symplectic-arxiv-daily/stargazers\n"))
            f.write((f"[issues-shield]: https://img.shields.io/github/issues/YassineAitMohamed/"
                     f"symplectic-arxiv-daily.svg?style=for-the-badge\n"))
            f.write((f"[issues-url]: https://github.com/YassineAitMohamed/"
                     f"symplectic-arxiv-daily/issues\n\n"))
                
    logging.info(f"{task} finished")        

def demo(**config):
    data_collector = []
    data_collector_web = []
    
    keywords = config['kv']
    max_results = config['max_results']
    publish_readme = config['publish_readme']
    publish_gitpage = config['publish_gitpage']
    publish_wechat = config['publish_wechat']
    show_badge = config['show_badge']

    b_update = config.get('update_paper_links', False)
    b_historical = config.get('historical_init', False)
    start_year = config.get('start_year', 1990)
    end_year = config.get('end_year', None)
    
    logging.info(f'Update Paper Link = {b_update}')
    logging.info(f'Historical Init = {b_historical}')
    
    if b_historical:
        logging.info(f"Starting HISTORICAL collection from {start_year}")
        for topic, keyword in keywords.items():
            logging.info(f"Historical collection for keyword: {topic}")
            data, data_web = get_historical_papers(
                topic=topic, 
                query=keyword, 
                start_year=start_year, 
                end_year=end_year,
                max_per_year=500
            )
            data_collector.append(data)
            data_collector_web.append(data_web)
            print("\n")
        logging.info(f"HISTORICAL collection completed")
        
    elif not b_update:
        logging.info(f"GET daily symplectic geometry papers begin")
        for topic, keyword in keywords.items():
            logging.info(f"Keyword: {topic}")
            data, data_web = get_daily_papers(topic, query=keyword, max_results=max_results)
            data_collector.append(data)
            data_collector_web.append(data_web)
            print("\n")
        logging.info(f"GET daily symplectic geometry papers end")

    if publish_readme:
        json_file = config['json_readme_path']
        md_file = config['md_readme_path']
        if config.get('update_paper_links', False):
            update_paper_links(json_file)
        else:    
            update_json_file(json_file, data_collector)
        json_to_md(json_file, md_file, task='Update Symplectic Geometry Readme', show_badge=show_badge)

    if publish_gitpage:
        json_file = config['json_gitpage_path']
        md_file = config['md_gitpage_path']
        if config.get('update_paper_links', False):
            update_paper_links(json_file)
        else:    
            update_json_file(json_file, data_collector)
        json_to_md(json_file, md_file, task='Update GitPage', to_web=True, use_title=False, show_badge=show_badge, use_tc=False, use_b2t=False)

    if publish_wechat:
        json_file = config['json_wechat_path']
        md_file = config['md_wechat_path']
        if config.get('update_paper_links', False):
            update_paper_links(json_file)
        else:    
            update_json_file(json_file, data_collector_web)
        json_to_md(json_file, md_file, task='Update Wechat', to_web=False, use_title=False, show_badge=show_badge)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config_path', type=str, default='config.yaml', 
                        help='configuration file path')
    parser.add_argument('--update_paper_links', default=False, action="store_true", 
                        help='whether to update paper links etc.')
    parser.add_argument('--historical_init', default=False, action="store_true", 
                        help='initialize with historical data from all years')
    parser.add_argument('--start_year', type=int, default=1990, 
                        help='start year for historical collection')
    parser.add_argument('--end_year', type=int, default=None, 
                        help='end year for historical collection (default: current year)')
                        
    args = parser.parse_args()
    config = load_config(args.config_path)
    config = {
        **config, 
        'update_paper_links': args.update_paper_links,
        'historical_init': args.historical_init,
        'start_year': args.start_year,
        'end_year': args.end_year
    }
    demo(**config)
