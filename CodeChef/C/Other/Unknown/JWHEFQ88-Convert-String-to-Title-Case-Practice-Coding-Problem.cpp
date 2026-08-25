Language: C++
1
2
3
4
5
6
7
8
9
10
11
12
13
14
15
16
17
18
19
20
21
22
23
24
25
26
27
28
29
30
31
32
33
34
35
36
37
38
39
40
41
42
43
44
45
46
47
48
#include <bits/stdc++.h>
using namespace std;
int main() {
    int T;
    cin >> T;
    cin.ignore();
        while(T--){
        string S;
        getline(cin,S);
                stringstream ss(S);
        string word;
        bool first = true ;
                while(ss >> word){
            if(!first) cout<< " ";
            first = false;
                        bool acronym = true;
                        for(char c : word){
                if(!isupper(c)){
                    acronym = false;
                    break;
                }
            }
                        if(acronym){
                cout<<word;
            }
            else{
                word[0] = toupper(word[0]);
                                for(int i = 1; i<word.size(); i++){
                    word[i] = tolower(word[i]);
                }
                cout<<word;
            }
        }
        cout<<'\n';
    }
        return 0;
}
